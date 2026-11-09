import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../../core/api/api_client.dart';
import '../../../core/models/analysis_models.dart';
import '../../../core/theme/app_theme.dart';
import 'source_notes.dart';

enum _GuideState { idle, loading, loaded, error }

/// "AI 설명 보기" 버튼 + 로컬 LLM이 생성한 대응 가이드 표시.
class AiGuideSection extends StatefulWidget {
  final List<String> drugIds;
  const AiGuideSection({super.key, required this.drugIds});

  @override
  State<AiGuideSection> createState() => _AiGuideSectionState();
}

class _AiGuideSectionState extends State<AiGuideSection> {
  _GuideState _state = _GuideState.idle;
  AnalysisGuideResponse? _guide;
  String? _error;

  Future<void> _fetchGuide() async {
    setState(() => _state = _GuideState.loading);
    try {
      // 로컬 LLM 콜드스타트(모델을 GPU에 새로 올림)는 87~153초 걸린다 — 백엔드
      // OLLAMA_TIMEOUT_SECONDS(200초)보다 짧게 잡으면 백엔드가 성공하기 전에
      // 여기서 먼저 끊겨버리므로, 항상 그보다 여유있게 잡는다.
      final res = await ApiClient.dio.post(
        'analysis/guide',
        data: {'drug_ids': widget.drugIds},
        options: Options(receiveTimeout: const Duration(seconds: 220)),
      );
      setState(() {
        _guide = AnalysisGuideResponse.fromJson(res.data);
        _state = _GuideState.loaded;
      });
    } on DioException catch (e) {
      setState(() {
        _error = describeDioError(e, 'AI 설명을 불러오지 못했습니다');
        _state = _GuideState.error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    switch (_state) {
      case _GuideState.idle:
        return OutlinedButton.icon(
          onPressed: _fetchGuide,
          icon: const Icon(Icons.auto_awesome_rounded, size: 18),
          label: const Text('AI 설명 보기'),
        );
      case _GuideState.loading:
        return Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(kRadius),
          ),
          child: Row(children: [
            const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                  'AI가 설명을 생성하는 중입니다',
                  style: TextStyle(
                      fontSize: 12.5,
                      height: 1.4,
                      color: scheme.onSurfaceVariant)),
            ),
          ]),
        );
      case _GuideState.error:
        return Row(children: [
          Expanded(
              child: Text(_error!,
                  style: TextStyle(color: scheme.error, fontSize: 13))),
          TextButton(onPressed: _fetchGuide, child: const Text('다시 시도')),
        ]);
      case _GuideState.loaded:
        final guide = _guide!;
        return Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: scheme.primaryContainer.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(kRadius),
            border: Border.all(
                color: scheme.primary.withValues(alpha: 0.25)),
          ),
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Icon(Icons.auto_awesome_rounded,
                      size: 16, color: scheme.primary),
                  const SizedBox(width: 6),
                  Text(guide.isAiGenerated ? 'AI 참고용 설명' : '안내',
                      style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                          color: scheme.primary)),
                ]),
                Gap.v8,
                Text(guide.guideText,
                    style: const TextStyle(fontSize: 13, height: 1.5)),
                if (guide.disclaimer.isNotEmpty) ...[
                  Gap.v8,
                  Text(guide.disclaimer,
                      style: TextStyle(
                          fontSize: 11,
                          color: scheme.onSurfaceVariant,
                          fontStyle: FontStyle.italic,
                          height: 1.4)),
                ],
                GuideSourceFooter(guide: guide),
              ]),
        );
    }
  }
}
