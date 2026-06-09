class LoginResponse {
  final String accessToken;
  final String refreshToken;

  LoginResponse.fromJson(Map<String, dynamic> j)
      : accessToken = j['access_token'],
        refreshToken = j['refresh_token'];
}
