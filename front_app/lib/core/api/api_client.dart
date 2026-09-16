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

        // check-and-set을 원자적으로 만들기 위해 await 없이 즉시 설정한다.
        // (아래 getRefreshToken()의 await 지점에서 이벤트 루프에 제어권이
        // 넘어가면 동시에 들어온 두 번째 401이 이 값을 null로 보고 중복
        // refresh를 시작할 수 있다.)
        final completer = Completer<String?>();
        _refreshCompleter = completer;

        final refresh = await TokenStorage.getRefreshToken();
        if (refresh == null) {
          await TokenStorage.clearTokens();
          _refreshCompleter = null;
          completer.complete(null);
          handler.next(error);
          return;
        }

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
          _refreshCompleter = null;
          completer.complete(newToken);
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

/// Dio 에러를 "서버가 보낸 detail 메시지" 우선으로 사람이 읽을 문자열로 바꾼다.
/// 여러 Provider가 거의 동일한 `'실패 (${e.response?.statusCode ?? "네트워크 오류"})'`
/// 패턴을 반복해 갖고 있던 것을 하나로 모은 것.
String describeDioError(DioException e, String fallback) {
  final data = e.response?.data;
  final detail = data is Map ? data['detail'] : null;
  if (detail is String && detail.isNotEmpty) return detail;
  return '$fallback (${e.response?.statusCode ?? '네트워크 오류'})';
}
