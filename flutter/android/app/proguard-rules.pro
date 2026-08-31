# google_mlkit_text_recognition references recognizer classes for every script
# (Chinese/Japanese/Devanagari/Korean), but this app only bundles the Korean
# model (text-recognition-korean). R8 can't verify the others exist, so tell
# it not to worry about them.
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
