import {
  combinePresetAndAppleSplashScreens,
  createAppleSplashScreens,
  defineConfig,
  minimal2023Preset,
} from "@vite-pwa/assets-generator/config";

// `npm run icons -w @adapt/frontend` regenerates PNG icons and iOS splash screens from the SVG
// brand mark. The printed <link> tags for splash screens live in index.html.
export default defineConfig({
  headLinkOptions: { preset: "2023" },
  preset: combinePresetAndAppleSplashScreens(
    {
      ...minimal2023Preset,
      maskable: { ...minimal2023Preset.maskable, padding: 0.2, resizeOptions: { background: "#0F1C2E" } },
      apple: { ...minimal2023Preset.apple, padding: 0.2, resizeOptions: { background: "#0F1C2E" } },
    },
    createAppleSplashScreens(
      {
        padding: 0.4,
        resizeOptions: { background: "#F5F4F0", fit: "contain" },
        darkResizeOptions: { background: "#0B1320", fit: "contain" },
        linkMediaOptions: { log: true, addMediaScreen: true, basePath: "/", xhtml: false },
        png: { compressionLevel: 9, quality: 70 },
      },
      ["iPhone 16 Pro Max", "iPhone 16 Pro", "iPhone 16", "iPhone 16e", "iPhone 13 mini", "iPhone SE 4.7\"", "iPhone 11", "iPad Air 10.9\"", "iPad Pro 12.9\""],
    ),
  ),
  images: ["public/brand-mark.svg"],
});
