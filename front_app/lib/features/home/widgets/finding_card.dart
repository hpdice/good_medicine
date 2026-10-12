import 'package:flutter/material.dart';
import '../../../core/models/analysis_models.dart';
import '../../../core/models/medicine_box_models.dart';
import '../../../core/theme/app_theme.dart';
import 'risk_badge.dart';

/// 약품 쌍(병용금기·효능군중복) 상호작용 카드.
class FindingCard extends StatefulWidget {
  final FindingItem finding;
  final Map<String, MedicineBoxDrug> drugsById;
  const FindingCard({super.key, required this.finding, required this.drugsById});

  @override
  State<FindingCard> createState() => _FindingCardState();
}

class _FindingCardState extends State<FindingCard> {
  bool _showIngredientDetail = false;

  @override
  Widget build(BuildContext context) {
    final finding = widget.finding;
    final drugsById = widget.drugsById;
    final scheme = Theme.of(context).colorScheme;
    final isDuplicateIngredient = finding.interactionType == 'duplicate_ingredient';
    final tone = isDuplicateIngredient || finding.interactionType == 'duplicate_effect_group'
        ? RiskTone.caution
        : RiskTone.critical;
    final style = RiskStyle.of(tone, Theme.of(context).brightness);
    final reasonLabel = isDuplicateIngredient
        ? '왜 주의해야 하나요'
        : tone == RiskTone.caution
            ? '중복 사유'
            : '금기 사유';
    final badgeText = isDuplicateIngredient
        ? '중복 복용'
        : tone == RiskTone.caution
            ? '같은 계열 중복'
            : style.label;
    final mechanismText = isDuplicateIngredient
        ? '${finding.mechanism} 처방받은 대로 복용 중이라면 약사·의사와 상담해 주세요.'
        : finding.mechanism;

    final drug1 = drugsById[finding.drug1Id];
    final drug2 = drugsById[finding.drug2Id];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${finding.drug1Name} × ${finding.drug2Name}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, fontSize: 14.5)),
            ),
            const SizedBox(width: 8),
            AppBadge(text: badgeText, color: style.color),
          ]),
          if (drug1?.efcyQesitm != null) ...[
            Gap.v8,
            DrugEfcyLine(name: finding.drug1Name, efcy: drug1!.efcyQesitm!),
          ],
          if (drug2?.efcyQesitm != null) ...[
            Gap.v4,
            DrugEfcyLine(name: finding.drug2Name, efcy: drug2!.efcyQesitm!),
          ],
          if (finding.riskTags.isNotEmpty) ...[
            Gap.v8,
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in finding.riskTags)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: style.container,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(t,
                        style: TextStyle(
                            fontSize: 11.5,
                            color: style.onContainer,
                            fontWeight: FontWeight.w600)),
                  ),
              ],
            ),
          ],
          if (finding.mechanism != null) ...[
            Gap.v8,
            Text(reasonLabel,
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: style.color)),
            const SizedBox(height: 2),
            Text(mechanismText!,
                style: TextStyle(
                    fontSize: 12.5, color: scheme.onSurfaceVariant, height: 1.4)),
          ],
          if (finding.hasIngredientDetail) ...[
            Gap.v8,
            InkWell(
              onTap: () =>
                  setState(() => _showIngredientDetail = !_showIngredientDetail),
              borderRadius: BorderRadius.circular(6),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(_showIngredientDetail ? '성분 상세 접기' : '어떤 성분이 금기인지 자세히 보기',
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: style.color)),
                  Icon(
                    _showIngredientDetail
                        ? Icons.keyboard_arrow_up
                        : Icons.keyboard_arrow_down,
                    size: 18,
                    color: style.color,
                  ),
                ],
              ),
            ),
            if (_showIngredientDetail) ...[
              const SizedBox(height: 4),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: style.container,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _IngredientLine(
                        drugName: finding.drug1Name,
                        ingrName: finding.ingrA!,
                        style: style),
                    const SizedBox(height: 4),
                    _IngredientLine(
                        drugName: finding.drug2Name,
                        ingrName: finding.ingrB!,
                        style: style),
                  ],
                ),
              ),
            ],
          ],
        ]),
      ),
    );
  }
}

class _IngredientLine extends StatelessWidget {
  final String drugName;
  final String ingrName;
  final RiskStyle style;
  const _IngredientLine(
      {required this.drugName, required this.ingrName, required this.style});

  @override
  Widget build(BuildContext context) {
    return RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12.5, color: style.onContainer, height: 1.4),
        children: [
          TextSpan(text: '$drugName  '),
          TextSpan(
              text: ingrName,
              style: const TextStyle(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class DrugEfcyLine extends StatelessWidget {
  final String name;
  final String efcy;
  const DrugEfcyLine({super.key, required this.name, required this.efcy});

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme.onSurfaceVariant;
    return RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12, color: c, height: 1.4),
        children: [
          TextSpan(
              text: '$name  ',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          TextSpan(text: efcy),
        ],
      ),
    );
  }
}
