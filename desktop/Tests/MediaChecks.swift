// Decode locally through the same Apple media/PDF frameworks as the native UI.
import Foundation
import AVFoundation
import PDFKit

@main struct MediaChecks {
    static func main() async throws {
        guard CommandLine.arguments.count == 3 else { fatalError("Pass a video and PDF") }
        let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
        let playable = try await asset.load(.isPlayable)
        let duration = try await asset.load(.duration)
        precondition(playable && duration.seconds > 0)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        let image = try await generator.image(at: .zero).image
        precondition(image.width > 0 && image.height > 0)
        let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[2]))
        precondition(document != nil && document!.pageCount > 0)
        precondition(document!.page(at: 0)!.thumbnail(of: CGSize(width: 128, height: 128), for: .mediaBox).size.width > 0)
        print("PASS native Apple video frame decode, duration, PDF open and rasterization")
    }
}
