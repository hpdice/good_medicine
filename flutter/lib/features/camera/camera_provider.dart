import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import '../../core/api/api_client.dart';
import '../../core/models/drug_models.dart';

class CameraProvider extends ChangeNotifier {
  List<DrugNameMatchResult> _matchResults = [];
  bool _isProcessing = false;
  bool _isAddingToBox = false;
  String? _error;
  int _addDoneCount = 0;

  List<DrugNameMatchResult> get matchResults => _matchResults;
  bool get isProcessing => _isProcessing;
  bool get isAddingToBox => _isAddingToBox;
  String? get error => _error;
  int get addDoneCount => _addDoneCount;

  Future<void> processImage(InputImage inputImage) async {
    _isProcessing = true;
    _error = null;
    notifyListeners();
    try {
      final recognizer = TextRecognizer(script: TextRecognitionScript.korean);
      late final RecognizedText result;
      try {
        result = await recognizer.processImage(inputImage);
      } finally {
        recognizer.close();
      }

      final candidates = _extractCandidates(result.text);
      if (candidates.isEmpty) {
        _error = '약품명을 찾을 수 없습니다. 직접 검색해 주세요.';
        _matchResults = [];
        return;
      }

      final res = await ApiClient.dio.post(
        'drugs/match-names',
        data: {'names': candidates},
      );
      _matchResults = (res.data as List)
          .map((e) => DrugNameMatchResult.fromJson(e))
          .toList();
    } on DioException catch (e) {
      _error = '매칭 실패 (${e.response?.statusCode})';
    } catch (e) {
      _error = 'OCR 오류: $e';
    } finally {
      _isProcessing = false;
      notifyListeners();
    }
  }

  Future<void> addDrugsToBox(List<String> drugIds) async {
    _isAddingToBox = true;
    _error = null;
    notifyListeners();
    final results = await Future.wait(
      drugIds.map((id) => ApiClient.dio
          .post('medicine-box', data: {'drug_id': id})
          .then((_) => true)
          .catchError((_) => false)),
    );
    _isAddingToBox = false;
    _addDoneCount = results.where((ok) => ok).length;
    if (_addDoneCount == 0) {
      _error = '약 추가에 실패했습니다. 다시 시도해 주세요.';
    }
    notifyListeners();
  }

  void resetAddDone() {
    _addDoneCount = 0;
    notifyListeners();
  }

  List<String> _extractCandidates(String text) {
    return text
        .split('\n')
        .map((l) => l.trim())
        .where((l) =>
            l.length >= 2 &&
            l.length <= 50 &&
            RegExp(r'[가-힣]').hasMatch(l) &&
            RegExp(r'[정캡슐주사액mg㎎]|\d+', caseSensitive: false).hasMatch(l))
        .take(20)
        .toList();
  }
}
