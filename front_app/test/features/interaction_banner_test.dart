import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:drugtest/core/models/analysis_models.dart';
import 'package:drugtest/features/home/widgets/interaction_banner.dart';

QuickCheckResponse _result({
  String level = 'safe',
  int total = 2,
  List<Map<String, String>> unresolved = const [],
  int contraindicated = 0,
}) =>
    QuickCheckResponse.fromJson({
      'total_drugs': total,
      'has_contraindication': contraindicated > 0,
      'risk_level': level,
      'contraindicated_count': contraindicated,
      'findings': [],
      'unresolved_drugs': unresolved,
    });

Widget _banner(QuickCheckResponse result) => MaterialApp(
      home: Scaffold(
        body: InteractionBanner(result: result, entries: const []),
      ),
    );

void main() {
  test('판정 응답의 판정하지 못한 약 목록을 읽고, 없으면 빈 목록이다', () {
    final res = _result(unresolved: [
      {'drug_id': 'd2', 'drug_name': '성분없는정'},
    ]);
    expect(res.unresolvedDrugs.single.drugId, 'd2');
    expect(res.unresolvedDrugs.single.drugName, '성분없는정');

    final old = QuickCheckResponse.fromJson({
      'total_drugs': 1,
      'has_contraindication': false,
      'risk_level': 'safe',
      'contraindicated_count': 0,
      'findings': [],
    });
    expect(old.unresolvedDrugs, isEmpty);
  });

  testWidgets('모든 약을 판정하지 못했으면 "위험 없음"이 아니라 "판정 불가"로 보여 준다', (tester) async {
    await tester.pumpWidget(_banner(_result(total: 1, unresolved: [
      {'drug_id': 'd1', 'drug_name': '성분없는정'},
    ])));
    expect(find.text('판정할 수 없는 약이에요'), findsOneWidget);
    expect(find.text('확인된 위험이 없어요'), findsNothing);
  });

  testWidgets('위험이 없어도 판정하지 못한 약이 있으면 개수를 알리고 상세에서 약 이름을 보여 준다', (tester) async {
    await tester.pumpWidget(_banner(_result(unresolved: [
      {'drug_id': 'd2', 'drug_name': '성분없는정'},
    ])));
    expect(find.text('확인된 위험이 없어요'), findsOneWidget);
    expect(find.textContaining('판정하지 못한 약 1개'), findsOneWidget);

    await tester.tap(find.text('확인된 위험이 없어요'));
    await tester.pumpAndSettle();
    expect(find.text('판정하지 못한 약 1개'), findsOneWidget);
    expect(find.text('성분없는정'), findsOneWidget);
    expect(find.text('판정 불가'), findsOneWidget);
  });

  testWidgets('판정하지 못한 약이 없는 위험 없음은 탭할 수 없다', (tester) async {
    await tester.pumpWidget(_banner(_result()));
    expect(find.text('확인된 위험이 없어요'), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
  });

  testWidgets('위험이 확인되면 그 등급을 그대로 보여 주고 판정하지 못한 약 수를 덧붙인다', (tester) async {
    await tester.pumpWidget(_banner(_result(
      level: 'critical',
      contraindicated: 1,
      unresolved: [
        {'drug_id': 'd3', 'drug_name': '성분없는정'},
      ],
    )));
    expect(find.text('병용금기 1건'), findsOneWidget);
    expect(find.textContaining('판정하지 못한 약 1개'), findsOneWidget);
    expect(find.text('판정할 수 없는 약이에요'), findsNothing);
  });
}
