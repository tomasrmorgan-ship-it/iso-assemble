import Cocoa
let dir=CommandLine.arguments[1]
try FileManager.default.createDirectory(atPath:dir,withIntermediateDirectories:true)
for size in [16,32,128,256,512] {
 for scale in [1,2] {
  let px=size*scale
  let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:px,pixelsHigh:px,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
  let context=NSGraphicsContext(bitmapImageRep:rep)!
  NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=context
  let s=CGFloat(px)
  NSColor(calibratedRed:0.12,green:0.16,blue:0.27,alpha:1).setFill()
  NSBezierPath(roundedRect:NSRect(x:s*0.05,y:s*0.05,width:s*0.9,height:s*0.9),xRadius:s*0.19,yRadius:s*0.19).fill()
  let colors:[NSColor]=[.systemTeal,.systemBlue,.systemIndigo,.systemPurple]
  for i in 0..<4 {
   colors[i].setFill();let x=s*(i%2==0 ? 0.19:0.52);let y=s*(i<2 ? 0.52:0.19)
   NSBezierPath(roundedRect:NSRect(x:x,y:y,width:s*0.29,height:s*0.29),xRadius:s*0.05,yRadius:s*0.05).fill()
  }
  NSColor.white.setFill();let tri=NSBezierPath();tri.move(to:NSPoint(x:s*0.43,y:s*0.34));tri.line(to:NSPoint(x:s*0.43,y:s*0.66));tri.line(to:NSPoint(x:s*0.67,y:s*0.5));tri.close();tri.fill()
  NSGraphicsContext.restoreGraphicsState()
  let suffix=scale==2 ? "@2x":""
  try rep.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:dir+"/icon_\(size)x\(size)\(suffix).png"))
 }
}
