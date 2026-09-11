import { createRequire } from "module";
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const require = createRequire(import.meta.url);
try {
  const path = require("path");
  const eslintEntry = require.resolve("eslint");
  const fileContextPath = path.join(path.dirname(eslintEntry), "linter", "file-context.js");
  const { FileContext } = require(fileContextPath);
  if (FileContext && !FileContext.prototype.getFilename) {
    FileContext.prototype.getFilename = function () {
      return this.filename;
    };
    FileContext.prototype.getSourceCode = function () {
      return this.sourceCode;
    };
    FileContext.prototype.getCwd = function () {
      return this.cwd;
    };
  }
} catch (e) {
  // Ignore if not present
}

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "eslint.config.mjs",
    "next.config.ts",
  ]),
]);

export default eslintConfig;
