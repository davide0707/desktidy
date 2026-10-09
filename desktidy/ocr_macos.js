// Text recognition with the macOS Vision framework (10.15+): free, offline, nothing is sent.
// Usage: osascript -l JavaScript ocr_macos.js image.png
// Prints the recognised lines (UTF-8); prints nothing when there is no text or Vision is not available.
ObjC.import("Foundation");
ObjC.import("Vision");

function run(argv) {
  const request = $.VNRecognizeTextRequest.alloc.init;
  request.recognitionLevel = 0; // VNRequestTextRecognitionLevelAccurate
  request.usesLanguageCorrection = true;
  try {
    // macOS 13+: the language of every line is detected (Italian accents, German umlauts...)
    request.automaticallyDetectsLanguage = true;
  } catch (e) {}
  try {
    // otherwise: the user's languages that Vision supports, English last
    const supported = request.supportedRecognitionLanguagesAndReturnError(null);
    const preferred = $.NSLocale.preferredLanguages;
    const chosen = [];
    for (let i = 0; i < preferred.count; i++) {
      const lang = preferred.objectAtIndex(i).js;
      for (let j = 0; j < supported.count; j++) {
        const s = supported.objectAtIndex(j).js;
        if (s.split("-")[0] === lang.split("-")[0] && chosen.indexOf(s) < 0) chosen.push(s);
      }
    }
    if (chosen.indexOf("en-US") < 0) chosen.push("en-US");
    request.recognitionLanguages = $(chosen);
  } catch (e) {}
  const url = $.NSURL.fileURLWithPath(argv[0]);
  const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $.NSDictionary.dictionary);
  if (!handler.performRequestsError($.NSArray.arrayWithObject(request), null)) return "";
  const results = request.results;
  const lines = [];
  for (let i = 0; i < results.count; i++) {
    const best = results.objectAtIndex(i).topCandidates(1);
    if (best.count > 0) lines.push(best.objectAtIndex(0).string.js);
  }
  return lines.join("\n");
}
