# MediaPipe Tasks Vision（本地托管）

白底拍摄功能使用的浏览器端人像分割运行时与模型，已随前端静态资源一起托管，避免运行时依赖第三方 CDN。

- npm 包：`@mediapipe/tasks-vision@1.2.2`
- 运行时：`vision_bundle.js`（即包内 `vision_bundle.mjs`）、`wasm/vision_wasm_internal.{js,wasm}`
- 模型：`selfie_segmenter.tflite`（Image Segmenter，float16，约 244 KB）
- 模型来源：<https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite>
- 去衣物模型：`selfie_multiclass_256x256.tflite`（Google MediaPipe SelfieMulticlass，float32，约 16 MB）。在浏览器内识别背景、头发、身体皮肤、面部皮肤、衣物和其他区域。去衣物白底模式仅填白模型判为背景或衣物的区域。
- 去衣物模型来源：<https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite>
- 许可证：Apache License 2.0，见 [LICENSE-APACHE.txt](LICENSE-APACHE.txt) 和 [SelfieMulticlass 模型卡](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Multiclass%20Segmentation.pdf)。

升级时请同时替换运行时、wasm 与模型，并在 `app.js` 中确认 `MP_BASE` 路径不变。
