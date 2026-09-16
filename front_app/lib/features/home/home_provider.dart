import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../core/api/api_client.dart';
import '../../core/models/analysis_models.dart';
import '../../core/models/medicine_box_models.dart';
import '../../core/notifications/medication_reminder_service.dart';

enum DrugRisk { none, safe, caution, contraindicated }

int _riskSeverity(DrugRisk r) => switch (r) {
      DrugRisk.contraindicated => 2,
      DrugRisk.caution => 1,
      _ => 0,
    };

class HomeProvider extends ChangeNotifier {
  List<MedicineBoxEntry> _entries = [];
  QuickCheckResponse? _checkResult;
  Map<String, DrugRisk> _riskMap = {};
  bool _isLoading = false;
  String? _error;

  List<MedicineBoxEntry> get entries => _entries;
  QuickCheckResponse? get checkResult => _checkResult;
  Map<String, DrugRisk> get riskMap => _riskMap;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadEntries() async {
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      final res = await ApiClient.dio.get('medicine-box');
      _entries =
          (res.data as List).map((e) => MedicineBoxEntry.fromJson(e)).toList();
      await _autoCheck();
      await MedicationReminderService.reschedule(_entries);
    } on DioException catch (e) {
      _error = describeDioError(e, '목록 불러오기 실패');
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> deleteEntry(String entryId) async {
    try {
      await ApiClient.dio.delete('medicine-box/$entryId');
      _entries = _entries.where((e) => e.id != entryId).toList();
      await _autoCheck();
      await MedicationReminderService.reschedule(_entries);
      notifyListeners();
    } on DioException catch (e) {
      _error = describeDioError(e, '삭제 실패');
      notifyListeners();
    }
  }

  /// 복용 시각/알림 on-off 등 복약함 항목 수정. 성공 시 목록을 갱신한다 —
  /// 알림 재스케줄은 이 갱신된 `_entries`를 구독하는 쪽(알림 서비스)에서 처리.
  Future<bool> updateEntry(String entryId, Map<String, dynamic> changes) async {
    try {
      final res =
          await ApiClient.dio.patch('medicine-box/$entryId', data: changes);
      final updated = MedicineBoxEntry.fromJson(res.data);
      _entries = [
        for (final e in _entries) e.id == entryId ? updated : e,
      ];
      await MedicationReminderService.reschedule(_entries);
      notifyListeners();
      return true;
    } on DioException catch (e) {
      _error = describeDioError(e, '수정 실패');
      notifyListeners();
      return false;
    }
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }

  Future<void> _autoCheck() async {
    final ids = _entries.map((e) => e.drug.id).toList();
    if (ids.length < 2) {
      _checkResult = null;
      _riskMap = {};
      return;
    }
    try {
      final res = await ApiClient.dio.post(
        'analysis/quick-check',
        data: {'drug_ids': ids},
      );
      _checkResult = QuickCheckResponse.fromJson(res.data);
      _buildRiskMap();
    } on DioException {
      // quick-check 실패는 비-차단 — 목록은 유지하고 상호작용 배너만 숨김
      _checkResult = null;
      _riskMap = {};
    }
  }

  void _buildRiskMap() {
    final result = _checkResult;
    if (result == null) return;
    _riskMap = {for (final e in _entries) e.drug.id: DrugRisk.safe};

    void bump(String id, DrugRisk risk) {
      final current = _riskMap[id] ?? DrugRisk.safe;
      if (_riskSeverity(risk) > _riskSeverity(current)) {
        _riskMap[id] = risk;
      }
    }

    for (final f in result.findings) {
      final risk = switch (f.interactionType) {
        'contraindicated' => DrugRisk.contraindicated,
        'duplicate_effect_group' => DrugRisk.caution,
        _ => null,
      };
      if (risk == null) continue;
      bump(f.drug1Id, risk);
      bump(f.drug2Id, risk);
    }
    // 알레르기 충돌·특정연령대금기는 병용금기와 같은 급(critical), 노인주의는
    // 효능군중복과 같은 급(caution) — 사용자 프로필(allergy_info/birth_year) 대
    // 약품 1개 단위 대조라 쌍이 아니라 해당 약 하나만 표시한다.
    for (final a in result.allergyConflicts) {
      bump(a.drugId, DrugRisk.contraindicated);
    }
    for (final a in result.ageCautions) {
      bump(a.drugId,
          a.ruleType == 'age_taboo' ? DrugRisk.contraindicated : DrugRisk.caution);
    }
  }
}
