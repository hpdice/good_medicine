import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../core/api/api_client.dart';
import '../../core/models/drug_models.dart';

class SearchProvider extends ChangeNotifier {
  String _query = '';
  List<DrugSearchResult> _results = [];
  bool _isLoading = false;
  String? _error;
  bool _addSuccess = false;
  CancelToken? _cancelToken;

  String get query => _query;
  List<DrugSearchResult> get results => _results;
  bool get isLoading => _isLoading;
  String? get error => _error;
  bool get addSuccess => _addSuccess;

  void updateQuery(String q) {
    _query = q;
    notifyListeners();
  }

  Future<void> search(String q) async {
    _cancelToken?.cancel();
    if (q.trim().isEmpty) {
      _results = [];
      notifyListeners();
      return;
    }
    _cancelToken = CancelToken();
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      final res = await ApiClient.dio.get('drugs',
          queryParameters: {'q': q, 'page': 1, 'limit': 20},
          cancelToken: _cancelToken);
      _results =
          (res.data as List).map((e) => DrugSearchResult.fromJson(e)).toList();
    } on DioException catch (e) {
      if (CancelToken.isCancel(e)) return;
      _error = '검색 실패 (${e.response?.statusCode ?? '네트워크 오류'})';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> addToBox(String drugId) async {
    try {
      await ApiClient.dio.post('medicine-box', data: {'drug_id': drugId});
      _addSuccess = true;
      notifyListeners();
    } on DioException catch (e) {
      _error = '추가 실패 (${e.response?.statusCode})';
      notifyListeners();
    }
  }

  void resetAddSuccess() {
    _addSuccess = false;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
