import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:drugtest/core/models/analysis_models.dart';
import 'package:drugtest/features/home/widgets/source_notes.dart';

AnalysisGuideResponse _guide({
  bool ai = true,
  String? model = 'qwen2.5:14b-instruct',
  List<Map<String, String>> sources = const [],
}) =>
    AnalysisGuideResponse.fromJson({
      'risk_level': 'critical',
      'guide_text': '설명',
      'is_ai_generated': ai,
      'model_name': model,
      'glossary_sources': sources,
    });

Widget _wrap(Widget child) => MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

void main() {
  testWidgets('정보 화면은 데이터 출처와 AI 설명 출처를 따로 적고 쓰지 않는 데이터는 적지 않는다', (tester) async {
    await tester.pumpWidget(_wrap(const SourceNotes()));
    expect(find.text('데이터 출처'), findsOneWidget);
    expect(find.text('AI 설명 출처'), findsOneWidget);
    expect(find.textContaining('식품의약품안전처'), findsOneWidget);
    expect(find.textContaining('건강보험심사평가원'), findsOneWidget);
    expect(find.textContaining('성분정보'), findsOneWidget);
    expect(find.textContaining('낱알식별'), findsNothing); // 제거된 기능의 데이터
    expect(find.textContaining('서울아산병원'), findsOneWidget);
    expect(find.textContaining('외부 AI 서비스로 보내지 않아요'), findsOneWidget);
  });

  test('모델 이름은 사람이 읽는 이름으로 바꾸고 모르는 이름은 그대로 둔다', () {
    expect(modelLabel('qwen2.5:14b-instruct'), 'Qwen2.5 14B');
    expect(modelLabel('llama3:8b'), 'llama3:8b');
    expect(modelLabel(null), '로컬 AI');
  });

  testWidgets('AI가 쓴 설명은 모델과 용어 풀이 출처를 이 설명 기준으로 보여 준다', (tester) async {
    await tester.pumpWidget(_wrap(GuideSourceFooter(
      guide: _guide(sources: [
        {'name': '서울아산병원 질환백과', 'url': 'https://example.org/a'},
        {'name': 'MSD 매뉴얼 일반인용 - 긴 QT 간격 증후군', 'url': 'https://example.org/b'},
      ]),
    )));
    expect(find.textContaining('Qwen2.5 14B'), findsOneWidget);
    expect(find.textContaining('서울아산병원 질환백과 · MSD 매뉴얼'), findsOneWidget);
  });

  testWidgets('AI가 쓰지 않은 안내 문구에는 AI·용어 풀이 출처를 붙이지 않는다', (tester) async {
    await tester.pumpWidget(_wrap(GuideSourceFooter(guide: _guide(ai: false, model: null))));
    expect(find.textContaining('작성:'), findsNothing);
    expect(find.textContaining('용어 풀이 출처'), findsNothing);
  });
}
