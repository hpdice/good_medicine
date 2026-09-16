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
