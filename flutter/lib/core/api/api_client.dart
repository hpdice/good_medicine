import 'dart:async';
import 'package:dio/dio.dart';
import '../storage/token_storage.dart';

class ApiClient {
  // 기본값: adb reverse tcp:8000 tcp:8000 (USB 연결)
  // 변경: flutter run --dart-define=BASE_URL=https://xxxx.ngrok-free.app/api/v1/
  static const baseUrl = String.fromEnvironment(
    'BASE_URL',
    defaultValue: 'http://127.0.0.1:8000/api/v1/',
  );

  static final Dio dio = _build();

  // 동시 401 처리: 첫 번째 refresh 완료를 기다렸다가 두 번째 요청도 재시도
  static Completer<String?>? _refreshCompleter;

  static Dio _build() {
    final dio = Dio(BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
    ));

    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        final token = await TokenStorage.getAccessToken();
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(options);
      },
      onError: (error, handler) async {
        final isUnauth = error.response?.statusCode == 401;
        final alreadyRetried =
            error.requestOptions.headers['X-Retry-After-Refresh'] != null;

        if (!isUnauth || alreadyRetried) {
          handler.next(error);
          return;
        }

        // 이미 refresh 중이면 완료될 때까지 대기
        if (_refreshCompleter != null) {
          final newToken = await _refreshCompleter!.future;
          if (newToken != null) {
            final opts = error.requestOptions
              ..headers['Authorization'] = 'Bearer $newToken'
              ..headers['X-Retry-After-Refresh'] = 'true';
            try {
              handler.resolve(await dio.fetch(opts));
            } catch (_) {
              handler.next(error);
            }
          } else {
            handler.next(error);
          }
          return;
        }

        final refresh = await TokenStorage.getRefreshToken();
        if (refresh == null) {
          await TokenStorage.clearTokens();
          handler.next(error);
          return;
        }

        _refreshCompleter = Completer();
        String? newToken;
        try {
          final res = await Dio().post(
            '${baseUrl}auth/refresh',
            data: {'refresh_token': refresh},
          );
          newToken = res.data['access_token'] as String;
          final newRefresh = res.data['refresh_token'] as String;
          await TokenStorage.saveTokens(newToken, newRefresh);
        } catch (_) {
          await TokenStorage.clearTokens();
        } finally {
          _refreshCompleter!.complete(newToken);
          _refreshCompleter = null;
        }

        if (newToken != null) {
          final opts = error.requestOptions
            ..headers['Authorization'] = 'Bearer $newToken'
            ..headers['X-Retry-After-Refresh'] = 'true';
          try {
            handler.resolve(await dio.fetch(opts));
          } catch (_) {
            handler.next(error);
          }
        } else {
          handler.next(error);
        }
      },
    ));

    return dio;
  }
}
