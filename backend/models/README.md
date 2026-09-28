# Local reconstruction vision assets

These models run on the Windows laptop's WSL CPU **before** CUDA training. No
capture is sent to Google. They are not included in the HarmonyOS package.

| File | Official source | SHA-256 | Use |
| --- | --- | --- | --- |
| `selfie_multiclass_256x256.tflite` | [Google MediaPipe SelfieMulticlass](https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite) | `c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0` | Hair, body skin, face skin probabilities; head mask |
| `face_landmarker.task` | [Google MediaPipe FaceLandmarker](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task) | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | Face location and broad envelope, including non-frontal views |

Downloaded 2026-09-26. The local code checks these exact bytes before use;
`latest` is not trusted to stay unchanged. Google documents the six-class
segmenter labels and model limitations in its [Image Segmenter guide](https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter).
The MediaPipe runtime is Apache-2.0; review model-asset distribution terms
separately before distributing these files outside this development workspace.

The mask is deliberately dilated around facial skin and hair. It is a guide
for COLMAP feature extraction and gsplat loss, not a proof of metric face
accuracy. A failed mask or pose gate must not fall back to a room reconstruction.
New source video and temporary masks are deleted after a completed or failed
job; only numeric quality metrics and finished assets remain.
