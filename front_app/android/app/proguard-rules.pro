# google_mlkit_text_recognition references recognizer classes for every script
# (Chinese/Japanese/Devanagari/Korean), but this app only bundles the Korean
# model (text-recognition-korean). R8 can't verify the others exist, so tell
# it not to worry about them.
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**

# flutter_local_notifications: 예약 알림을 Gson(TypeToken)으로 저장·복원한다. R8이 제네릭 정보와 이 클래스들을 지우면
# 릴리스 APK에서만 예약이 실패하고 알림이 안 온다(디버그 빌드에서는 재현되지 않음).
-keep class com.dexterous.flutterlocalnotifications.** { *; }
-keepattributes Signature
-keepattributes *Annotation*
-keep class * extends com.google.gson.reflect.TypeToken
-keep,allowobfuscation,allowshrinking class com.google.gson.reflect.TypeToken
