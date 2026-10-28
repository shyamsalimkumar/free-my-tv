// Fits photos to the TV's 1920 × 1080 screen for the screensaver (webos/photos.py): upright, and a JPEG each.
// Each shows whole: a larger one shrinks to fit, a smaller one keeps its size (never stretched), and the rest of the
// screen is a calm color of its own, its average toned down. A photo that repeats an earlier one (the same photo
// again, or a near copy: Apple's Vision rates how alike) is skipped. Up to <most> made. Prints a line a photo: the
// name it made, or "skip", its file and the earlier one's, between tabs:
//
//     swift webos/photo_fit.swift <folder for them> <most> <photo> ...
import CoreImage
import Foundation
import Vision

let width: CGFloat = 1920, height: CGFloat = 1080
let frame = CGRect(x: 0, y: 0, width: width, height: height)
let args = CommandLine.arguments
guard args.count >= 4, let most = Int(args[2]) else { exit(2) }
let into = URL(fileURLWithPath: args[1])
// Vision's feature print distance: a resized, recompressed copy measured 0.17; a 15% crop, a 3° tilt or another
// picture in the same style 0.22 and up. Under this, it's the same photo.
let REPEAT: Float = 0.2
let context = CIContext()
let sRGB = CGColorSpace(name: CGColorSpace.sRGB)!

/// The image at `scale`, centered on the screen.
func centered(_ image: CIImage, scale: CGFloat) -> CIImage {
    let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    let e = scaled.extent
    return scaled.transformed(by: CGAffineTransform(translationX: (width - e.width) / 2 - e.minX,
                                                    y: (height - e.height) / 2 - e.minY))
}

/// The photo's average color, half way to gray and dark: close to the photo, but quieter than anything in it.
func surround(_ photo: CIImage) -> CIColor {
    var rgba = [UInt8](repeating: 0, count: 4)
    let average = photo.applyingFilter("CIAreaAverage", parameters: [kCIInputExtentKey: CIVector(cgRect: photo.extent)])
    context.render(average, toBitmap: &rgba, rowBytes: 4, bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                   format: .RGBA8, colorSpace: sRGB)
    let r = CGFloat(rgba[0]) / 255, g = CGFloat(rgba[1]) / 255, b = CGFloat(rgba[2]) / 255
    let gray = 0.2126 * r + 0.7152 * g + 0.0722 * b
    func quiet(_ c: CGFloat) -> CGFloat { return (c + gray) / 2 * 0.45 }
    return CIColor(red: quiet(r), green: quiet(g), blue: quiet(b), colorSpace: sRGB)!
}

func featurePrint(_ photo: CIImage) -> VNFeaturePrintObservation? {
    let request = VNGenerateImageFeaturePrintRequest()
    try? VNImageRequestHandler(ciImage: photo, options: [:]).perform([request])
    return request.results?.first
}

/// The earlier photo this one repeats, if any.
func repeats(_ print: VNFeaturePrintObservation, of kept: [(String, VNFeaturePrintObservation)]) -> String? {
    for (name, other) in kept {
        var distance: Float = 0
        if (try? print.computeDistance(&distance, to: other)) != nil && distance < REPEAT { return name }
    }
    return nil
}

var made = 0
var kept: [(String, VNFeaturePrintObservation)] = []
for path in args.dropFirst(3) where made < most {
    guard let photo = CIImage(contentsOf: URL(fileURLWithPath: path), options: [.applyOrientationProperty: true]) else {
        continue
    }
    let file = (path as NSString).lastPathComponent
    if let print = featurePrint(photo) {
        if let earlier = repeats(print, of: kept) {
            Swift.print("skip\t\(file)\t\(earlier)")
            continue
        }
        kept.append((file, print))
    }
    let e = photo.extent
    let scale = min(1, width / e.width, height / e.height)
    let screen = centered(photo, scale: scale).composited(over: CIImage(color: surround(photo)).cropped(to: frame))
    made += 1
    let name = String(format: "%03d.jpg", made)
    do {
        let quality = [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.82]
        try context.writeJPEGRepresentation(of: screen.cropped(to: frame), to: into.appendingPathComponent(name),
                                            colorSpace: sRGB, options: quality)
        print(name)
    } catch {
        made -= 1
    }
}
