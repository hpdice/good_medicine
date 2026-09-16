import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../core/api/api_client.dart';
import '../../core/models/drug_models.dart';

/// 사용자가 업로드/촬영한 사진 한 장의 기록. **클라이언트에만** 남는다 —
/// 서버는 OCR 후 이미지를 폐기하므로, 되돌아보기용 사본은 여기(앱 메모리)뿐이다.
class SubmittedPhoto {
  final Uint8List bytes;
  final DateTime at;
  final int candidateCount;
  final int matchedCount;

  SubmittedPhoto({
    required this.bytes,
    required this.at,
    required this.candidateCount,
    required this.matchedCount,
  });
}

class CameraProvider extends ChangeNotifier {
  List<DrugNameMatchResult> _matchResults = [];
  bool _isProcessing = false;
  bool _isAdding = false;
  String? _error;
  int _addDoneCount = 0;
  final List<SubmittedPhoto> _history = [];

  static const _historyLimit = 12;

  List<DrugNameMatchResult> get matchResults => _matchResults;
  bool get isProcessing => _isProcessing;
  bool get isAdding => _isAdding;
  String? get error => _error;
  int get addDoneCount => _addDoneCount;

  /// 이번 세션에 올린 사진들 (최신순). 앱을 닫으면 사라진다.
  List<SubmittedPhoto> get history => List.unmodifiable(_history);

  /// 사진 바이트를 서버 OCR 엔드포인트로 보내 약품명을 매칭한다.
  /// 이미지는 서버에서 메모리로만 처리되고 저장되지 않는다.
  Future<void> processImageBytes(
    Uint8List bytes, {
    required String filename,
  }) async {
    _isProcessing = true;
    _error = null;
    _matchResults = [];
    notifyListeners();
    try {
      // contentType은 생략 — dio가 application/octet-stream으로 보내고,
      // 서버(PIL)가 실제 바이트로 이미지 여부를 검증한다(415 처리).
      final form = FormData.fromMap({
        'image': MultipartFile.fromBytes(
          bytes,
          filename: filename.isEmpty ? 'prescription.jpg' : filename,
        ),
      });
      // OCR은 회전·색상 재시도 때문에 다른 API보다 오래 걸릴 수 있어(최악 케이스 약
      // 10초대) 기본 10초 타임아웃보다 여유를 둔다.
      final res = await ApiClient.dio.post(
        'drugs/ocr',
        data: form,
        options: Options(
          sendTimeout: const Duration(seconds: 30),
          receiveTimeout: const Duration(seconds: 30),
        ),
      );
      final data = res.data as Map<String, dynamic>;
      final candidates = (data['candidates'] as List? ?? []);
      _matchResults = (data['matches'] as List? ?? [])
          .map((e) => DrugNameMatchResult.fromJson(e as Map<String, dynamic>))
          .toList();

      _history.insert(
        0,
        SubmittedPhoto(
          bytes: bytes,
          at: DateTime.now(),
          candidateCount: candidates.length,
          matchedCount: _matchResults.where((m) => m.matched != null).length,
        ),
      );
      if (_history.length > _historyLimit) _history.removeLast();

      if (candidates.isEmpty) {
        _error = '약품명을 찾을 수 없습니다. 직접 검색해 주세요.';
      }
    } on DioException catch (e) {
      final code = e.response?.statusCode;
      _error = switch (code) {
        413 => '이미지가 너무 큽니다. 더 작은 사진으로 다시 시도해 주세요.',
        415 => '이미지 파일이 아닙니다.',
        503 => 'OCR 서버를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        _ => '사진 분석 실패 ($code)',
      };
    } catch (e) {
      _error = '사진 분석 오류: $e';
    } finally {
      _isProcessing = false;
      notifyListeners();
    }
  }

  Future<void> addDrugsToBox(List<String> drugIds) async {
    _isAdding = true;
    _error = null;
    notifyListeners();
    final results = await Future.wait(
      drugIds.map((id) => ApiClient.dio
          .post('medicine-box', data: {'drug_id': id})
          .then((_) => true)
          .catchError((_) => false)),
    );
    _isAdding = false;
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

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
