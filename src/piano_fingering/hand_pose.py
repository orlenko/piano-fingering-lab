"""Stage 5: Full-rate two-hand pose extraction (Apple Vision + coordinate/chirality contract)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any

import av

from .models import FramePose, HandObservation

SWIFT_VISION_EXTRACTOR_SRC = r"""
import AVFoundation
import Foundation
import Vision

struct JointOut: Codable {
    let x: Double
    let y: Double
    let c: Double
}

struct HandOut: Codable {
    let chirality: String
    let confidence: Double
    let joints: [String: JointOut]
}

struct FrameOut: Codable {
    let frameIndex: Int
    let rawPtsSec: Double
    let ptsSec: Double
    let width: Int
    let height: Int
    let hands: [HandOut]
}

let args = CommandLine.arguments
guard args.count >= 3 else {
    fputs("Usage: hand_pose_extractor <video_path> <out_json_path>\n", stderr)
    exit(2)
}

let videoURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])

let asset = AVURLAsset(url: videoURL)
guard let track = asset.tracks(withMediaType: .video).first else {
    fputs("No video track found\n", stderr)
    exit(1)
}

let reader = try AVAssetReader(asset: asset)
let outputSettings: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA)
]
let trackOutput = AVAssetReaderTrackOutput(track: track, outputSettings: outputSettings)
trackOutput.alwaysCopiesSampleData = false
reader.add(trackOutput)

guard reader.startReading() else {
    fputs("Failed to start AVAssetReader: \(String(describing: reader.error))\n", stderr)
    exit(1)
}

let jointMap: [(VNHumanHandPoseObservation.JointName, String)] = [
    (.wrist, "wrist"),
    (.thumbCMC, "thumb_cmc"),
    (.thumbMP, "thumb_mcp"),
    (.thumbIP, "thumb_ip"),
    (.thumbTip, "thumb_tip"),
    (.indexMCP, "index_mcp"),
    (.indexPIP, "index_pip"),
    (.indexDIP, "index_dip"),
    (.indexTip, "index_tip"),
    (.middleMCP, "middle_mcp"),
    (.middlePIP, "middle_pip"),
    (.middleDIP, "middle_dip"),
    (.middleTip, "middle_tip"),
    (.ringMCP, "ring_mcp"),
    (.ringPIP, "ring_pip"),
    (.ringDIP, "ring_dip"),
    (.ringTip, "ring_tip"),
    (.littleMCP, "little_mcp"),
    (.littlePIP, "little_pip"),
    (.littleDIP, "little_dip"),
    (.littleTip, "little_tip"),
]

var frames: [FrameOut] = []
var firstPts: Double? = nil
var idx = 0

while let sampleBuffer = trackOutput.copyNextSampleBuffer() {
    autoreleasepool {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let rawSec = CMTimeGetSeconds(pts)
        if firstPts == nil {
            firstPts = rawSec
        }
        let relSec = rawSec - (firstPts ?? 0.0)

        let request = VNDetectHumanHandPoseRequest()
        request.maximumHandCount = 2
        request.revision = VNDetectHumanHandPoseRequestRevision1

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)

        do {
            // Decode raw unrotated pixelBuffer (.up) matching PyAV raw frame buffer coordinates
            let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .up, options: [:])
            try handler.perform([request])
        } catch {
            fputs("Vision error at frame \(idx): \(error)\n", stderr)
        }

        var handOuts: [HandOut] = []
        if let results = request.results {
            for obs in results {
                let chir: String
                switch obs.chirality {
                case .left: chir = "L"
                case .right: chir = "R"
                default: chir = "unknown"
                }
                var jDict: [String: JointOut] = [:]
                if let allPts = try? obs.recognizedPoints(.all) {
                    for (vnName, keyName) in jointMap {
                        if let pt = allPts[vnName] {
                            jDict[keyName] = JointOut(x: pt.location.x, y: pt.location.y, c: Double(pt.confidence))
                        }
                    }
                }
                handOuts.append(HandOut(chirality: chir, confidence: Double(obs.confidence), joints: jDict))
            }
        }

        frames.append(FrameOut(
            frameIndex: idx,
            rawPtsSec: rawSec,
            ptsSec: relSec,
            width: width,
            height: height,
            hands: handOuts
        ))
        idx += 1
    }
}

let encoder = JSONEncoder()
let data = try encoder.encode(frames)
try data.write(to: outURL)
"""

FINGERTIP_JOINTS = {
    1: "thumb_tip",
    2: "index_tip",
    3: "middle_tip",
    4: "ring_tip",
    5: "little_tip",
}


def compute_dorsal_palm_cross(
    landmarks: dict[str, tuple[float, float, float] | None],
    min_joint_conf: float = 0.2,
) -> tuple[float, float]:
    """Compute signed 2D dorsal metacarpal cross product in top-left (+x right, +y down) coords.

    Formula:
        a = middle_mcp - wrist
        b = little_mcp - index_mcp
        c_palm = a_x * b_y - a_y * b_x

    For a palm-down hand viewed from above (+y downward):
        c_palm > 0 => anatomical Right ("R")
        c_palm < 0 => anatomical Left  ("L")
    Invariant to arbitrary 2D camera rotation (including 180 deg behind-music-desk view)
    and unaffected by thumb-under-finger crossings.

    Returns:
        (raw_cross_px2, normalized_sin_theta in [-1, 1]).
    """
    req = ("wrist", "middle_mcp", "index_mcp", "little_mcp")
    pts: dict[str, tuple[float, float]] = {}
    for k in req:
        val = landmarks.get(k)
        if val is None or val[2] < min_joint_conf:
            return 0.0, 0.0
        pts[k] = (val[0], val[1])

    ax = pts["middle_mcp"][0] - pts["wrist"][0]
    ay = pts["middle_mcp"][1] - pts["wrist"][1]
    bx = pts["little_mcp"][0] - pts["index_mcp"][0]
    by = pts["little_mcp"][1] - pts["index_mcp"][1]

    cross = ax * by - ay * bx
    norm = ((ax * ax + ay * ay) ** 0.5) * ((bx * bx + by * by) ** 0.5)
    if norm < 1e-3:
        return 0.0, 0.0
    return float(cross), float(cross / norm)


def resolve_hand_chirality(
    detector_chirality: str,
    norm_palm_cross: float,
    min_sin_margin: float = 0.14,
) -> str:
    """Combine dorsal knuckle-arch geometry with detector chirality."""
    if abs(norm_palm_cross) >= min_sin_margin:
        geom_hand = "R" if norm_palm_cross > 0.0 else "L"
        if detector_chirality in ("L", "R") and detector_chirality != geom_hand:
            # Strong palm arch geometry wins if very well-conditioned; otherwise mark ambiguous
            if abs(norm_palm_cross) >= 0.32:
                return geom_hand
            return "ambiguous"
        return geom_hand
    if detector_chirality in ("L", "R"):
        return detector_chirality
    return "ambiguous"


def _compile_swift_extractor(cache_bin_dir: Path) -> Path:
    cache_bin_dir.mkdir(parents=True, exist_ok=True)
    src_hash = hashlib.sha256(SWIFT_VISION_EXTRACTOR_SRC.encode("utf-8")).hexdigest()[:12]
    bin_path = cache_bin_dir / f"hand_pose_extractor_{src_hash}"
    if bin_path.exists():
        return bin_path

    src_path = cache_bin_dir / f"hand_pose_extractor_{src_hash}.swift"
    src_path.write_text(SWIFT_VISION_EXTRACTOR_SRC, encoding="utf-8")
    subprocess.run(
        ["swiftc", "-O", str(src_path), "-o", str(bin_path)],
        check=True,
    )
    return bin_path


def extract_full_rate_hand_poses(
    video_path: str | Path,
    out_json_path: str | Path | None = None,
    cache_dir: str | Path = ".local/cache",
    expected_size: tuple[int, int] | None = None,
    helper_path: Path | None = None,
) -> tuple[list[FramePose], dict[str, Any]]:
    """Run full-frame Apple Vision 2-hand pose detection with top-left pixel conversion."""
    t0 = time.perf_counter()
    if expected_size is None:
        container = av.open(str(video_path))
        try:
            v_stream = next(s for s in container.streams if s.type == "video")
            expected_size = (
                int(v_stream.codec_context.width),
                int(v_stream.codec_context.height),
            )
        finally:
            container.close()

    cache_p = Path(cache_dir)
    bin_path = Path(helper_path) if helper_path is not None else _compile_swift_extractor(cache_p / "bin")
    if not bin_path.is_file():
        raise FileNotFoundError("The bundled hand-tracking component is missing.")
    raw_out = cache_p / "raw_vision_poses.json"

    subprocess.run(
        [str(bin_path), str(video_path), str(raw_out)],
        check=True,
    )

    raw_frames = json.loads(raw_out.read_text(encoding="utf-8"))
    frame_poses: list[FramePose] = []

    two_hand_frames = 0
    one_hand_frames = 0
    zero_hand_frames = 0
    chirality_agreements = 0
    chirality_checks = 0
    ambiguous_hands = 0

    for rf in raw_frames:
        w = int(rf["width"])
        h = int(rf["height"])
        if expected_size is not None and (w, h) != expected_size:
            raise ValueError(
                f"Swift Vision frame dimensions {(w, h)} do not match PyAV {expected_size}"
            )

        hands_obs: list[HandObservation] = []
        raw_hands = rf.get("hands", [])
        for det_i, rh in enumerate(raw_hands):
            det_chir = str(rh.get("chirality", "unknown"))
            h_conf = float(rh.get("confidence", 0.0))
            j_raw = rh.get("joints", {})

            landmarks: dict[str, tuple[float, float, float] | None] = {}
            for j_name, j_val in j_raw.items():
                jc = float(j_val["c"])
                # Filter Apple Vision's confidence == 0 sentinel duplicate fallback coordinates
                if jc <= 0.001:
                    landmarks[j_name] = None
                else:
                    # Convert Vision bottom-left normalized (x_vn, y_vn) -> top-left pixels
                    x_px = float(j_val["x"]) * float(w)
                    y_px = (1.0 - float(j_val["y"])) * float(h)
                    landmarks[j_name] = (round(x_px, 3), round(y_px, 3), round(jc, 4))

            raw_cross, norm_cross = compute_dorsal_palm_cross(landmarks)
            resolved = resolve_hand_chirality(det_chir, norm_cross)

            if det_chir in ("L", "R") and abs(norm_cross) >= 0.14:
                chirality_checks += 1
                geom_hand = "R" if norm_cross > 0 else "L"
                if geom_hand == det_chir:
                    chirality_agreements += 1
            if resolved == "ambiguous":
                ambiguous_hands += 1

            hands_obs.append(
                HandObservation(
                    det_index=det_i,
                    detector_chirality=det_chir,
                    resolved_hand=resolved,
                    palm_cross=round(norm_cross, 4),
                    hand_confidence=round(h_conf, 4),
                    landmarks=landmarks,
                )
            )

        # If 2 hands detected and one is ambiguous while the other is strongly L/R with opposite palm_cross,
        # keep conservative unless palm_cross clearly separates them
        if len(hands_obs) == 2:
            two_hand_frames += 1
            if (
                hands_obs[0].resolved_hand == hands_obs[1].resolved_hand
                and hands_obs[0].resolved_hand in ("L", "R")
            ):
                # Duplicate chirality on 2 detections: resolve only if opposite palm_cross signs, else mark lower-margin one ambiguous
                c0, c1 = hands_obs[0].palm_cross, hands_obs[1].palm_cross
                if c0 * c1 < -0.02:
                    hands_obs[0].resolved_hand = "R" if c0 > 0 else "L"
                    hands_obs[1].resolved_hand = "R" if c1 > 0 else "L"
                else:
                    weaker = 0 if abs(c0) <= abs(c1) else 1
                    hands_obs[weaker].resolved_hand = "ambiguous"
                    ambiguous_hands += 1
        elif len(hands_obs) == 1:
            one_hand_frames += 1
        else:
            zero_hand_frames += 1

        frame_poses.append(
            FramePose(
                frame_index=int(rf["frameIndex"]),
                pts_sec=round(float(rf["ptsSec"]), 6),
                width=w,
                height=h,
                hands=hands_obs,
            )
        )

    elapsed = time.perf_counter() - t0
    meta: dict[str, Any] = {
        "backend": "apple_vision_vn_hand_pose_rev1",
        "frame_count": len(frame_poses),
        "runtime_sec": round(elapsed, 3),
        "two_hand_frames": two_hand_frames,
        "one_hand_frames": one_hand_frames,
        "zero_hand_frames": zero_hand_frames,
        "palm_cross_vs_vision_chirality_checks": chirality_checks,
        "palm_cross_vs_vision_chirality_agreements": chirality_agreements,
        "palm_cross_agreement_rate": (
            round(chirality_agreements / chirality_checks, 4) if chirality_checks else None
        ),
        "ambiguous_hand_instances": ambiguous_hands,
    }

    if out_json_path is not None:
        out_p = Path(out_json_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(
                {
                    "metadata": meta,
                    "frames": [fp.to_dict() for fp in frame_poses],
                },
                indent=2,
            )
        )

    return frame_poses, meta
