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
        if (isUnauth && !alreadyRetried) {
          final refresh = await TokenStorage.getRefreshToken();
          if (refresh != null) {
            try {
              final res = await Dio().post(
                '${baseUrl}auth/refresh',
                data: {'refresh_token': refresh},
              );
              final newToken = res.data['access_token'] as String;
              final newRefresh = res.data['refresh_token'] as String;
              await TokenStorage.saveTokens(newToken, newRefresh);
              final opts = error.requestOptions
                ..headers['Authorization'] = 'Bearer $newToken'
                ..headers['X-Retry-After-Refresh'] = 'true';
              final retried = await dio.fetch(opts);
              return handler.resolve(retried);
            } catch (_) {
              await TokenStorage.clearTokens();
            }
          }
        }
        handler.next(error);
      },
    ));

    return dio;
  }
}
