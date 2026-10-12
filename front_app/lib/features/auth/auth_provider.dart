import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../core/api/api_client.dart';
import '../../core/storage/token_storage.dart';

enum AuthStatus { idle, loading, success, error }

class AuthProvider extends ChangeNotifier {
  AuthStatus _status = AuthStatus.idle;
  String? _errorMessage;

  AuthStatus get status => _status;
  String? get errorMessage => _errorMessage;

  Future<void> login(String email, String password) async {
    _set(AuthStatus.loading);
    try {
      final res = await ApiClient.dio.post('auth/login', data: {
        'email': email,
        'password': password,
      });
      await TokenStorage.saveTokens(
          res.data['access_token'], res.data['refresh_token']);
      _set(AuthStatus.success);
    } on DioException catch (e) {
      _setError(describeDioError(e, '로그인 실패'));
    }
  }

  Future<void> register(String email, String password, String name) async {
    _set(AuthStatus.loading);
    try {
      await ApiClient.dio.post('auth/register', data: {
        'email': email,
        'password': password,
        'name': name,
        'privacy_consent': true,
        'health_data_consent': true,
      });
      await login(email, password);
    } on DioException catch (e) {
      _setError(describeDioError(e, '회원가입 실패'));
    }
  }

  /// 서버에 refresh token 폐기를 요청한 뒤 기기의 토큰을 지운다.
  /// 서버 호출이 실패(오프라인 등)해도 기기에서는 항상 로그아웃된다.
  /// 토큰을 지우면 라우터의 redirect가 /login으로 보낸다.
  Future<void> logout() async {
    final refresh = await TokenStorage.getRefreshToken();
    if (refresh != null) {
      try {
        await ApiClient.dio
            .post('auth/logout', data: {'refresh_token': refresh});
      } on DioException {
        // 서버 폐기는 실패해도 로컬 로그아웃은 진행한다.
      }
    }
    await TokenStorage.clearTokens();
    _set(AuthStatus.idle);
  }

  void resetState() => _set(AuthStatus.idle);

  void _set(AuthStatus s) {
    _status = s;
    if (s != AuthStatus.error) _errorMessage = null;
    notifyListeners();
  }

  void _setError(String msg) {
    _status = AuthStatus.error;
    _errorMessage = msg;
    notifyListeners();
  }
}
