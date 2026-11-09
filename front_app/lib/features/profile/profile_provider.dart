import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../core/api/api_client.dart';
import '../../core/models/user_models.dart';

enum ProfileStatus { idle, loading, saving, error }

class ProfileProvider extends ChangeNotifier {
  UserProfile? _profile;
  ProfileStatus _status = ProfileStatus.idle;
  String? _error;

  UserProfile? get profile => _profile;
  ProfileStatus get status => _status;
  String? get error => _error;

  /// 로그아웃 시 이전 사용자의 정보가 다음 로그인에 비치지 않도록 비운다.
  void clear() {
    _profile = null;
    _status = ProfileStatus.idle;
    _error = null;
    notifyListeners();
  }

  Future<void> load() async {
    _status = ProfileStatus.loading;
    _error = null;
    notifyListeners();
    try {
      final res = await ApiClient.dio.get('users/me');
      _profile = UserProfile.fromJson(res.data);
      _status = ProfileStatus.idle;
    } on DioException catch (e) {
      _error = describeDioError(e, '내 정보를 불러오지 못했습니다');
      _status = ProfileStatus.error;
    }
    notifyListeners();
  }

  /// 전부 선택 입력 — null이면 그 필드는 보내지 않는다(값 없음 유지),
  /// 빈 리스트를 보내면 서버에 저장된 값을 비운다. 출생연도는 [clearBirthYear]가 true이고 값이 없을 때
  /// 명시적 null을 보내 서버에 저장된 값을 지운다.
  Future<bool> save({
    List<String>? healthConditions,
    int? birthYear,
    bool clearBirthYear = false,
    bool? isPregnant,
  }) async {
    _status = ProfileStatus.saving;
    _error = null;
    notifyListeners();
    try {
      final res = await ApiClient.dio.patch('users/me', data: {
        if (healthConditions != null) 'health_conditions': healthConditions,
        if (birthYear != null || clearBirthYear) 'birth_year': birthYear,
        if (isPregnant != null) 'is_pregnant': isPregnant,
      });
      _profile = UserProfile.fromJson(res.data);
      _status = ProfileStatus.idle;
      notifyListeners();
      return true;
    } on DioException catch (e) {
      _error = describeDioError(e, '저장 실패');
      _status = ProfileStatus.error;
      notifyListeners();
      return false;
    }
  }
}
