import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../core/api/api_client.dart';
import '../../core/models/analysis_models.dart';
import '../../core/models/medicine_box_models.dart';

enum DrugRisk { none, safe, contraindicated }

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
    } on DioException catch (e) {
      _error = '목록 불러오기 실패 (${e.response?.statusCode})';
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
      notifyListeners();
    } on DioException catch (e) {
      _error = '삭제 실패 (${e.response?.statusCode})';
      notifyListeners();
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
    } catch (_) {}
  }

  void _buildRiskMap() {
    final result = _checkResult;
    if (result == null) return;
    _riskMap = {for (final e in _entries) e.drug.id: DrugRisk.safe};
    for (final f in result.findings) {
      _riskMap[f.drug1Id] = DrugRisk.contraindicated;
      _riskMap[f.drug2Id] = DrugRisk.contraindicated;
    }
  }
}
