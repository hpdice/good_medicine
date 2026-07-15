import 'dart:async';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import '../api/api_client.dart';

/// FCM 초기화 및 토큰을 백엔드(`fcm_token`)에 등록한다.
///
/// Firebase 네이티브 설정(google-services.json 등)이 아직 연동되지 않은
/// 환경에서도 앱 전체가 정상 동작해야 하므로, 모든 단계는 실패 시
/// 예외를 앱 밖으로 전파하지 않고 조용히 건너뛴다.
class FcmService {
  static bool _initialized = false;
  static String? _lastRegisteredToken;
  static StreamSubscription<String>? _refreshSub;

  /// 홈 화면 진입마다 호출된다 (탭 전환으로 재마운트될 때도 포함).
  /// 이미 등록된 토큰과 동일하면 서버 재등록을 건너뛴다.
  static Future<void> initializeAndRegister() async {
    if (!_initialized) {
      try {
        await Firebase.initializeApp();
        await FirebaseMessaging.instance.requestPermission();
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

  static Future<void> _sendTokenToBackend(String token) async {
    try {
      await ApiClient.dio.patch('users/me', data: {'fcm_token': token});
      _lastRegisteredToken = token;
    } catch (e) {
      debugPrint('FCM 토큰 서버 등록 실패: $e');
    }
  }
}
