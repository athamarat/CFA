import PDFKit
let d = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1]))!
var out = ""
for i in 0..<d.pageCount { out += "\n=== PAGE \(i+1) ===\n" + (d.page(at: i)?.string ?? "") }
try! out.write(toFile: CommandLine.arguments[2], atomically: true, encoding: .utf8)
