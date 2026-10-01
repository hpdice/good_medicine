import 'package:flutter/material.dart';
import '../../../core/models/analysis_models.dart';
import '../../../core/models/medicine_box_models.dart';
import '../../../core/theme/app_theme.dart';
import 'ai_guide_section.dart';
import 'finding_card.dart';
import 'single_drug_risk_card.dart';

/// 배너 라벨을 "병용금기 1건 · 알레르기 1건" 식으로 조립한다. 노인주의는 같은
/// caution 등급이라도 효능군중복과 뭉뚱그리면 경고 인플레이션이 생기니 별도 문구로 둔다.
String _summaryLabel(QuickCheckResponse result) {
  final parts = <String>[
    if (result.contraindicatedCount > 0) '병용금기 ${result.contraindicatedCount}건',
    if (result.allergyConflicts.isNotEmpty) '알레르기 ${result.allergyConflicts.length}건',
    if (result.ageTabooCount > 0) '연령금기 ${result.ageTabooCount}건',
    if (result.duplicateEffectGroupCount > 0) '효능군 중복 ${result.duplicateEffectGroupCount}건',
    if (result.elderlyCautionCount > 0) '노인 주의 ${result.elderlyCautionCount}건',
  ];
  return parts.isEmpty ? '주의가 필요해요' : parts.join(' · ');
}

/// 홈 화면 상단의 위험도 요약 배너. 탭하면 상세 상호작용 시트를 연다.
class InteractionBanner extends StatelessWidget {
  final QuickCheckResponse result;
  final List<MedicineBoxEntry> entries;
  const InteractionBanner({super.key, required this.result, required this.entries});

  @override
  Widget build(BuildContext context) {
    final tone = RiskStyle.toneFromLevel(result.riskLevel) ?? RiskTone.safe;
    final style = RiskStyle.of(tone, Theme.of(context).brightness);
    final isSafe = tone == RiskTone.safe;

    // 걸린 규칙이 없다는 건 "DUR에 등록된 위험이 없다"는 뜻이지 안전 보증이 아니다
    // (예: 와파린은 DUR 병용금기 등록이 0건). 그래서 "괜찮아요"로 단정하지 않는다.
    final label = isSafe ? '확인된 위험이 없어요' : _summaryLabel(result);
    final subLabel =
        isSafe ? 'DUR에 등록된 조합만 확인돼요 · 걱정되면 약사와 상담하세요' : '탭하여 상세 보기';

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(kRadius),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            style.color,
            Color.lerp(style.color, Colors.black, 0.18)!,
          ],
        ),
        boxShadow: [
          BoxShadow(
            color: style.color.withValues(alpha: 0.35),
            blurRadius: 20,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: isSafe ? null : () => _showFindings(context, result, entries),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            child: Row(children: [
              Container(
                padding: const EdgeInsets.all(9),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.18),
                  shape: BoxShape.circle,
                ),
                child: Icon(style.icon, color: Colors.white, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label,
                        style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                            fontSize: 15.5,
                            letterSpacing: -0.2)),
                    Text(subLabel,
                        style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.9),
                            fontSize: 12.5)),
                  ],
                ),
              ),
              if (!isSafe)
                const Icon(Icons.chevron_right_rounded, color: Colors.white),
            ]),
          ),
        ),
      ),
    );
  }

  void _showFindings(BuildContext context, QuickCheckResponse result,
      List<MedicineBoxEntry> entries) {
    final drugsById = {for (final e in entries) e.drug.id: e.drug};
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.55,
        maxChildSize: 0.9,
        builder: (_, ctrl) => ListView(
          controller: ctrl,
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
          children: [
            Text('상호작용 상세',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700)),
            Gap.v12,
            for (final f in result.findings)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: FindingCard(finding: f, drugsById: drugsById),
              ),
            for (final a in result.allergyConflicts)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: SingleDrugRiskCard(
                  drugName: a.drugName,
                  tone: RiskTone.critical,
                  reasonLabel: '알레르기 성분',
                  reasonText: '등록한 알레르기 "${a.matchedAllergyTerm}"와(과) '
                      '겹치는 성분(${a.matchedIngredient})이 있습니다.',
                ),
              ),
            for (final a in result.ageCautions)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: SingleDrugRiskCard(
                  drugName: a.drugName,
                  tone: a.ruleType == 'age_taboo'
                      ? RiskTone.critical
                      : RiskTone.caution,
                  reasonLabel: a.ruleType == 'age_taboo' ? '특정연령대금기' : '노인 주의',
                  reasonText: a.prohibitContent ?? '등록한 나이 기준에 해당하는 DUR 규칙입니다.',
                ),
              ),
            Gap.v8,
            AiGuideSection(
              drugIds: {for (final e in entries) e.drug.id}.toList(),
            ),
          ],
        ),
      ),
    );
  }
}
