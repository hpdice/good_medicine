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

/// 백그라운드(앱 종료/최소화)에서 FCM 메시지를 수신하는 top-level 핸들러.
/// Firebase는 이 함수를 별도 isolate에서 실행하므로 자체적으로 초기화가 필요하다.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
}

/// FCM 초기화 및 토큰을 백엔드(`fcm_token`)에 등록한다.
///
/// Firebase 네이티브 설정(google-services.json 등)이 아직 연동되지 않은
/// 환경에서도 앱 전체가 정상 동작해야 하므로, 모든 단계는 실패 시
/// 예외를 앱 밖으로 전파하지 않고 조용히 건너뛴다.
class FcmService {
  static bool _initialized = false;
  static String? _lastRegisteredToken;
  static StreamSubscription<String>? _refreshSub;
  static final _localNotifications = FlutterLocalNotificationsPlugin();

  /// 홈 화면 진입마다 호출된다 (탭 전환으로 재마운트될 때도 포함).
  /// 이미 등록된 토큰과 동일하면 서버 재등록을 건너뛴다.
  static Future<void> initializeAndRegister() async {
    if (!_initialized) {
      try {
        // main()에서 이미 초기화했을 수 있으므로 중복 초기화(duplicate-app
        // 예외)를 피한다.
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

  /// 앱이 포그라운드일 때는 FCM이 notification payload를 자동 표시하지
  /// 않으므로, 로컬 알림으로 직접 띄운다.
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
