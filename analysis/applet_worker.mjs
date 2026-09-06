import fs from "node:fs";
import { build } from "esbuild";

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const result = await build({
  stdin: {
    contents: payload.source,
    loader: "ts",
    sourcefile: "visualization-applet.ts",
    resolveDir: "/opt/sandbox",
  },
  bundle: true,
  write: false,
  format: "iife",
  globalName: "SchedulingApplet",
  platform: "browser",
  target: "es2020",
  sourcemap: false,
  minify: true,
});

process.stdout.write(JSON.stringify({
  status: "success",
  bundle: result.outputFiles[0].text,
}));
