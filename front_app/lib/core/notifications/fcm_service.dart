import 'dart:async';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import '../api/api_client.dart';

const _channel = AndroidNotificationChannel(
  'drug_interaction_alerts',
  '병용금기 알림',
  description: '약물 상호작용 위험 알림',
  importance: Importance.high,
);

/// 앱이 종료/최소화된 상태에서 FCM 메시지를 받는 핸들러. Firebase가 이걸
/// 별도 isolate에서 돌리기 때문에 여기서 다시 초기화를 해줘야 한다.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
}

/// FCM 초기화하고 토큰을 백엔드(`fcm_token`)에 등록.
///
/// google-services.json 같은 Firebase 네이티브 설정이 아직 안 붙어 있어도
/// 앱 자체는 돌아가야 해서, 실패해도 예외를 밖으로 던지지 않고 그냥 넘어간다.
class FcmService {
  static bool _initialized = false;
  static String? _lastRegisteredToken;
  static StreamSubscription<String>? _refreshSub;
  static final _localNotifications = FlutterLocalNotificationsPlugin();

  /// 홈 화면 들어갈 때마다 호출됨(탭 전환으로 재마운트되는 경우도 포함).
  /// 토큰이 이전에 등록한 것과 같으면 서버에 다시 보내지 않는다.
  static Future<void> initializeAndRegister() async {
    if (!_initialized) {
      try {
        // main()에서 이미 초기화됐을 수 있어서 중복 초기화 예외(duplicate-app) 방지
        if (Firebase.apps.isEmpty) {
          await Firebase.initializeApp();
        }
        await FirebaseMessaging.instance.requestPermission();
        await _initLocalNotifications();
        FirebaseMessaging.onMessage.listen(_showForegroundNotification);
        _initialized = true;
      } catch (e) {
        debugPrint('FCM 초기화 건너뜀 (Firebase 미설정): $e');
        return;
      }
    }

    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null && token != _lastRegisteredToken) {
        await _sendTokenToBackend(token);
      }
    } catch (e) {
      debugPrint('FCM 토큰 조회 실패: $e');
    }

    _refreshSub ??=
        FirebaseMessaging.instance.onTokenRefresh.listen(_sendTokenToBackend);
  }

  static Future<void> _initLocalNotifications() async {
    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    await _localNotifications.initialize(
      const InitializationSettings(android: androidInit),
    );
    await _localNotifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(_channel);
  }

  /// 포그라운드에서는 FCM이 notification payload를 알아서 띄워주지
  /// 않아서 로컬 알림으로 직접 표시해야 한다.
  static void _showForegroundNotification(RemoteMessage message) {
    final notification = message.notification;
    if (notification == null) return;
    _localNotifications.show(
      notification.hashCode,
      notification.title,
      notification.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          _channel.id,
          _channel.name,
          channelDescription: _channel.description,
          importance: Importance.high,
          priority: Priority.high,
        ),
      ),
    );
  }

  static Future<void> _sendTokenToBackend(String token) async {
    try {
      await ApiClient.dio.patch('users/me', data: {'fcm_token': token});
      _lastRegisteredToken = token;
    } catch (e) {
      debugPrint('FCM 토큰 서버 등록 실패: $e');
    }
  }
}
