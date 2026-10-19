import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:drugtest/core/models/medicine_box_models.dart';
import 'package:drugtest/features/home/home_provider.dart';
import 'package:drugtest/features/home/widgets/medicine_card.dart';

MedicineBoxEntry _entry({String? efcy, String? atpn}) =>
    MedicineBoxEntry.fromJson({
      'id': 'e1',
      'drug': {
        'id': 'd1',
        'item_name': '테스트정',
        'efcy_qesitm': efcy,
        'atpn_qesitm': atpn,
      },
      'intake_times': <String>[],
      'reminder_enabled': false,
      'is_current': true,
      'added_method': 'manual',
      'created_at': '2026-10-19T00:00:00Z',
    });

Widget _card(MedicineBoxEntry entry) => MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: SizedBox(
            width: 320,
            child: MedicineCard(
              entry: entry,
              risk: DrugRisk.none,
              isExpanded: true,
              onToggle: () {},
              onDelete: () {},
              onEditReminder: () {},
            ),
          ),
        ),
      ),
    );

void main() {
  final longText = List.generate(
          12, (i) => '${i + 1}) 심혈관계 위험이 있을 수 있으므로 신중하게 투여하여야 한다.')
      .join('\n');

  testWidgets('긴 주의사항은 앞부분만 보이고 더보기로 펼쳐진다', (tester) async {
    // 펼친 본문이 기본 테스트 화면(600px)보다 길어서 접기 버튼이 화면 밖으로 밀리므로 화면을 키운다.
    tester.view.physicalSize = const Size(800, 3000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_card(_entry(efcy: '골관절증의 증상 완화', atpn: longText)));

    expect(find.text('더보기'), findsOneWidget);
    expect(find.text('접기'), findsNothing);
    // 접힌 상태에서는 앞 항목만 그려진다 — 마지막 항목은 줄임 처리되어 높이가 작다.
    final collapsedHeight = tester.getSize(find.text(longText)).height;

    await tester.tap(find.text('더보기'));
    await tester.pumpAndSettle(); // 카드의 AnimatedCrossFade 크기 애니메이션이 끝나야 버튼이 눌린다

    expect(find.text('접기'), findsOneWidget);
    expect(find.text('더보기'), findsNothing);
    final expandedHeight = tester.getSize(find.text(longText)).height;
    expect(expandedHeight, greaterThan(collapsedHeight * 2));

    await tester.tap(find.text('접기'));
    await tester.pumpAndSettle();
    expect(find.text('더보기'), findsOneWidget);
  });

  testWidgets('문단 사이 빈 줄은 줄 수에 안 세어 짧은 글에 더보기가 안 뜬다', (tester) async {
    // 문단 3개 + 사이 빈 줄 = 5줄이지만 실제 내용은 3줄 — 4줄 한도를 안 넘는다.
    const text = '첫째 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다.';
    await tester.pumpWidget(_card(_entry(efcy: '골관절증의 증상 완화', atpn: text)));

    expect(find.text('더보기'), findsNothing);
    expect(find.text('첫째 문단입니다.\n둘째 문단입니다.\n셋째 문단입니다.'), findsOneWidget);
  });

  testWidgets('짧은 글에는 더보기 버튼이 없다', (tester) async {
    await tester.pumpWidget(_card(_entry(efcy: '골관절증의 증상 완화', atpn: '술을 피하세요.')));

    expect(find.text('더보기'), findsNothing);
    expect(find.text('접기'), findsNothing);
    expect(find.text('술을 피하세요.'), findsOneWidget);
  });
}
