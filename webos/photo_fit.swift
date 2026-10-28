// Fits photos to the TV's 1920 × 1080 screen for the screensaver (webos/photos.py): upright, and a JPEG each.
// Each shows whole: a larger one shrinks to fit, a smaller one keeps its size (never stretched), and the rest of the
// screen is a calm color of its own, its average toned down. Prints the names it made, one a line:
//
//     swift webos/photo_fit.swift <folder for them> <photo> ...
import CoreImage
import Foundation

let width: CGFloat = 1920, height: CGFloat = 1080
let frame = CGRect(x: 0, y: 0, width: width, height: height)
let args = CommandLine.arguments
guard args.count >= 3 else { exit(2) }
let into = URL(fileURLWithPath: args[1])
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

var made = 0
for path in args.dropFirst(2) {
    guard let photo = CIImage(contentsOf: URL(fileURLWithPath: path), options: [.applyOrientationProperty: true]) else {
        continue
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
