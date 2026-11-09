import 'package:flutter/material.dart';
import '../../../core/models/analysis_models.dart';
import '../../../core/theme/app_theme.dart';

/// 로컬 모델 이름("qwen2.5:14b-instruct")을 사람이 읽는 이름으로 — 모르는 이름은 그대로 쓴다.
String modelLabel(String? model) {
  if (model == null || model.isEmpty) return '로컬 AI';
  final m = RegExp(r'^qwen([\d.]+):(\d+)b', caseSensitive: false).firstMatch(model);
  return m == null ? model : 'Qwen${m.group(1)} ${m.group(2)}B';
}

/// 정보 대화상자 — 데이터 출처와 AI 설명 출처를 따로 적는다.
/// 위험도 판정은 앞쪽(데이터)만으로 정해지고, AI는 정해진 판정을 풀어 쓰기만 한다.
class SourceNotes extends StatelessWidget {
  const SourceNotes({super.key});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final headStyle = TextStyle(
        fontWeight: FontWeight.w700, fontSize: 13, color: scheme.primary);
    final orgStyle = TextStyle(
        fontWeight: FontWeight.w600, fontSize: 12.5, color: scheme.onSurface);
    final bodyStyle = TextStyle(
        fontSize: 12.5, height: 1.55, color: scheme.onSurfaceVariant);

    Widget bullet(String text) => Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('·  ', style: bodyStyle),
              Expanded(child: Text(text, style: bodyStyle)),
            ],
          ),
        );

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('데이터 출처', style: headStyle),
        const SizedBox(height: 4),
        Text('위험도 판정은 아래 공공데이터의 규칙으로 정해져요. AI는 판정에 관여하지 않아요.',
            style: bodyStyle),
        const SizedBox(height: 8),
        Text('식품의약품안전처 · 공공데이터포털', style: orgStyle),
        bullet('의약품개요정보 (e약은요)'),
        bullet('의약품 제품 허가정보 (목록·상세)'),
        bullet('의약품안전사용서비스(DUR) 품목정보 — 병용금기 · 효능군중복 · 특정연령대금기 · 노인주의 · 임부금기'),
        bullet('의약품안전사용서비스(DUR) 성분정보 — 병용금기 · 효능군중복 · 연령 · 용량주의, 성분 코드'),
        const SizedBox(height: 8),
        Text('건강보험심사평가원 · 공공데이터포털', style: orgStyle),
        bullet('의약품표준코드 · 의약품주성분 — 약과 성분 연결, 정·캡슐 1개당 함량, 제형'),
        const SizedBox(height: 18),
        Text('AI 설명 출처', style: headStyle),
        const SizedBox(height: 4),
        Text('"AI 설명 보기"를 눌렀을 때만 나와요.', style: bodyStyle),
        bullet('작성: 서비스 서버에서 돌아가는 로컬 AI(Qwen2.5 14B)가 이미 정해진 판정을 쉬운 말로 풀어 써요. 외부 AI 서비스로 보내지 않아요.'),
        bullet('근거: 위 공공데이터의 판정 결과와 약 정보. 일부 의학 용어 풀이는 서울아산병원 · MSD 매뉴얼 일반인용 · 질병관리청 국가건강정보포털 문서를 근거로 해요.'),
        bullet('AI가 일반 상식을 섞을 수 있어요. 참고용으로만 보세요.'),
        const SizedBox(height: 18),
        Text('안내', style: headStyle),
        bullet('병용 위험 정보는 참고용이며 의학적 진단·처방이 아닙니다.'),
        bullet('DUR에 등록되지 않은 상호작용은 표시되지 않을 수 있습니다.'),
        bullet('복약 전 반드시 의사·약사와 상담하세요.'),
      ],
    );
  }
}

/// AI 설명 카드 아래의 출처 표기 — 어떤 AI가 썼고 어떤 용어 풀이를 근거로 했는지 이 설명 기준으로 밝힌다.
class GuideSourceFooter extends StatelessWidget {
  final AnalysisGuideResponse guide;
  const GuideSourceFooter({super.key, required this.guide});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final style = TextStyle(
        fontSize: 11, height: 1.4, color: scheme.onSurfaceVariant);
    final lines = <String>[
      if (guide.isAiGenerated)
        '작성: ${modelLabel(guide.modelName)} (서비스 서버의 로컬 AI) · 판정은 식약처 DUR 규칙으로 정해졌고 AI는 풀어 쓰기만 했어요',
      if (guide.glossarySources.isNotEmpty)
        '용어 풀이 출처: ${guide.glossarySources.map((s) => s.name).join(' · ')}',
    ];
    if (lines.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Gap.v8,
        Text(lines.join('\n'), style: style),
      ],
    );
  }
}
