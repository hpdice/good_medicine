import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:drugtest/core/theme/app_theme.dart';
import 'package:drugtest/features/home/widgets/single_drug_risk_card.dart';

Widget _card({String? badgeLabel, RiskTone tone = RiskTone.critical}) => MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 320,
          child: SingleDrugRiskCard(
            drugName: '테스트정',
            tone: tone,
            badgeLabel: badgeLabel,
            reasonLabel: '내 건강 상태: 고혈압',
            reasonText: '이 약의 허가사항에 있어요.',
          ),
        ),
      ),
    );

void main() {
  testWidgets('배지에 카드 종류가 나오고 등급 라벨("병용금기")이 나오지 않는다', (tester) async {
    await tester.pumpWidget(_card(badgeLabel: '건강 상태 금기'));
    expect(find.text('건강 상태 금기'), findsOneWidget);
    expect(find.text('병용금기'), findsNothing);
  });

  testWidgets('주의 등급 카드도 "효능군 중복"이 아니라 종류를 보여 준다', (tester) async {
    await tester.pumpWidget(_card(badgeLabel: '노인 주의', tone: RiskTone.caution));
    expect(find.text('노인 주의'), findsOneWidget);
    expect(find.text('효능군 중복'), findsNothing);
  });

  testWidgets('종류를 안 정하면 기존처럼 등급 라벨을 쓴다', (tester) async {
    await tester.pumpWidget(_card());
    expect(find.text('병용금기'), findsOneWidget);
  });
}
