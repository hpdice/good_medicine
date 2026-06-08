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
    final lines = text.split('\n').map((l) => l.trim()).toList();

    // 약품명(정/캡슐 등으로 끝) + 다음 줄이 순수 용량(20mg)이면 합친다
    final drugFormEnd = RegExp(r'(정|캡슐|주사|액|시럽|연고|크림)$');
    final dosageOnly = RegExp(r'^\d+(\.\d+)?(mg|㎎|mcg|μg|g|ml|mL)$', caseSensitive: false);
    final merged = <String>[];
    for (int i = 0; i < lines.length; i++) {
      if (drugFormEnd.hasMatch(lines[i]) &&
          i + 1 < lines.length &&
          dosageOnly.hasMatch(lines[i + 1])) {
        merged.add(lines[i] + lines[i + 1]);
        i++;
      } else {
        merged.add(lines[i]);
      }
    }

    // 약품명 패턴: 剂型+숫자 | 숫자+단위 | 剂型으로 끝나는 이름(낙센에프정 등)
    final drugPattern = RegExp(
      r'(정|캡슐|주사|액|시럽|연고|크림)\d|\d+(mg|㎎|mcg|μg|g|ml|mL)\b|(정|캡슐|주사|액|시럽|연고|크림)$',
      caseSensitive: false,
    );
    return merged
        .where((l) =>
            l.length >= 2 &&
            l.length <= 50 &&
            RegExp(r'[가-힣]').hasMatch(l) &&
            drugPattern.hasMatch(l))
        .take(20)
        .toList();
  }
}
