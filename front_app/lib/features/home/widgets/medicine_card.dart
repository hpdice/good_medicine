import 'package:flutter/material.dart';
import '../../../core/models/medicine_box_models.dart';
import '../../../core/theme/app_theme.dart';
import '../home_provider.dart';

/// 복약함 카드 — 약 이름/효능, 위험도 점, 알림·삭제 버튼, 펼치면 효능 상세.
class MedicineCard extends StatelessWidget {
  final MedicineBoxEntry entry;
  final DrugRisk risk;
  final bool isExpanded;
  final VoidCallback onToggle;
  final VoidCallback onDelete;
  final VoidCallback onEditReminder;

  const MedicineCard({
    super.key,
    required this.entry,
    required this.risk,
    required this.isExpanded,
    required this.onToggle,
    required this.onDelete,
    required this.onEditReminder,
  });

  static const List<(String, String? Function(MedicineBoxDrug))> _detailFields = [
    ('효능', _efcy),
    ('이렇게 복용하세요', _useMethod),
    ('경고', _atpnWarn),
    ('주의사항', _atpn),
    ('함께 먹으면 안 되는 음식·약', _intrc),
    ('이런 증상이 나타날 수 있어요', _se),
    ('보관 방법', _depositMethod),
  ];
  static String? _efcy(MedicineBoxDrug d) => d.efcyQesitm;
  static String? _useMethod(MedicineBoxDrug d) => d.useMethodQesitm;
  static String? _atpnWarn(MedicineBoxDrug d) => d.atpnWarnQesitm;
  static String? _atpn(MedicineBoxDrug d) => d.atpnQesitm;
  static String? _intrc(MedicineBoxDrug d) => d.intrcQesitm;
  static String? _se(MedicineBoxDrug d) => d.seQesitm;
  static String? _depositMethod(MedicineBoxDrug d) => d.depositMethodQesitm;

  List<(String, String)> _sectionsFor(MedicineBoxDrug drug) => _detailFields
      .map((f) => (f.$1, f.$2(drug)))
      .where((s) => s.$2 != null && s.$2!.isNotEmpty)
      .map((s) => (s.$1, s.$2!))
      .toList();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final drug = entry.drug;
    final sections = _sectionsFor(drug);
    return Card(
      child: InkWell(
        onTap: sections.isEmpty ? null : onToggle,
        borderRadius: BorderRadius.circular(kRadius),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 6, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              RiskDot(risk: risk),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(drug.displayName,
                          style: const TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 15)),
                      if (drug.className != null) ...[
                        const SizedBox(height: 2),
                        Text(drug.className!,
                            style: TextStyle(
                                fontSize: 12,
                                color: scheme.onSurfaceVariant)),
                      ],
                      if (entry.doseLabel case final dose?) ...[
                        const SizedBox(height: 2),
                        Text(dose,
                            style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                                color: scheme.primary)),
                      ],
                      if (drug.efcyQesitm != null && !isExpanded) ...[
                        const SizedBox(height: 3),
                        Text(drug.efcyQesitm!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                                fontSize: 12,
                                color: scheme.onSurfaceVariant)),
                      ],
                    ]),
              ),
              if (drug.etcOtcName != null)
                Container(
                  margin: const EdgeInsets.only(right: 2),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: scheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(drug.etcOtcName!,
                      style: TextStyle(
                          fontSize: 11, color: scheme.onSurfaceVariant)),
                ),
              IconButton(
                icon: Icon(
                  entry.reminderEnabled
                      ? Icons.alarm_on_rounded
                      : Icons.alarm_add_outlined,
                  size: 20,
                  color: entry.reminderEnabled
                      ? scheme.primary
                      : scheme.onSurfaceVariant,
                ),
                tooltip: '복용량·알림 설정',
                onPressed: onEditReminder,
              ),
              IconButton(
                icon: Icon(Icons.delete_outline_rounded,
                    size: 20, color: scheme.onSurfaceVariant),
                onPressed: onDelete,
              ),
            ]),
            AnimatedCrossFade(
              duration: const Duration(milliseconds: 180),
              crossFadeState: isExpanded
                  ? CrossFadeState.showSecond
                  : CrossFadeState.showFirst,
              firstChild: const SizedBox(width: double.infinity),
              secondChild: _buildExpandedDetail(context, sections),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _buildExpandedDetail(BuildContext context, List<(String, String)> sections) {
    if (sections.isEmpty) return const SizedBox(width: double.infinity);

    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 10, 8, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Divider(height: 1),
          const SizedBox(height: 8),
          for (int i = 0; i < sections.length; i++) ...[
            if (i > 0) const SizedBox(height: 10),
            if (sections.length > 1) ...[
              Text(sections[i].$1,
                  style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: scheme.primary)),
              const SizedBox(height: 3),
            ],
            _CollapsibleText(
              sections[i].$2,
              style: TextStyle(
                  fontSize: 12.5, height: 1.45, color: scheme.onSurfaceVariant),
            ),
          ],
        ],
      ),
    );
  }
}

/// 긴 설명은 앞부분(4줄)만 보여주고 "더보기"로 펼친다.
/// 식약처 허가사항 원문(주의사항 등)은 의·약사용 문체로 수백~천 자라, 카드를 펼치면
/// 다른 항목이 화면 밖으로 밀려난다. 넘치지 않는 짧은 글엔 버튼이 안 뜬다.
class _CollapsibleText extends StatefulWidget {
  final String text;
  final TextStyle style;

  const _CollapsibleText(this.text, {required this.style});

  static const int previewLines = 4;

  @override
  State<_CollapsibleText> createState() => _CollapsibleTextState();
}

class _CollapsibleTextState extends State<_CollapsibleText> {
  bool _expanded = false;

  // 원문에는 문단 사이 빈 줄이 흔하다(e약은요 약 절반 이상) — 그대로 두면 4줄 한도의 절반을
  // 빈 줄이 먹어서 문단 2개만 보이고 나머지가 접힌다. 줄바꿈을 한 번으로 모은다.
  late final String _text =
      widget.text.trim().replaceAll(RegExp(r'\s*\n\s*'), '\n');

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final painter = TextPainter(
        text: TextSpan(text: _text, style: widget.style),
        maxLines: _CollapsibleText.previewLines,
        textDirection: Directionality.of(context),
        textScaler: MediaQuery.textScalerOf(context),
      )..layout(maxWidth: constraints.maxWidth);
      final overflows = painter.didExceedMaxLines;
      final collapsed = overflows && !_expanded;

      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // ellipsis는 maxLines가 있을 때만 건다 — maxLines 없이 ellipsis만 주면 한 줄로 잘린다
        // (펼쳤는데 오히려 카드가 줄어드는 버그를 위젯 테스트가 잡았다).
        Text(_text,
            style: widget.style,
            maxLines: collapsed ? _CollapsibleText.previewLines : null,
            overflow: collapsed ? TextOverflow.ellipsis : TextOverflow.clip),
        if (overflows)
          // 소제목('경고' 등)과 같은 굵은 청록 글씨면 내용 없는 제목처럼 읽힌다 — 화살표를 붙여
          // 누르는 버튼으로 보이게 하고 글씨는 소제목보다 가볍게 둔다.
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.only(top: 6, bottom: 2),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Text(_expanded ? '접기' : '더보기',
                    style: widget.style.copyWith(
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                        color: Theme.of(context).colorScheme.primary)),
                Icon(
                    _expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    size: 18,
                    color: Theme.of(context).colorScheme.primary),
              ]),
            ),
          ),
      ]);
    });
  }
}

class RiskDot extends StatelessWidget {
  final DrugRisk risk;
  const RiskDot({super.key, required this.risk});

  @override
  Widget build(BuildContext context) {
    final b = Theme.of(context).brightness;
    final (RiskStyle? style) = switch (risk) {
      DrugRisk.contraindicated => RiskStyle.of(RiskTone.critical, b),
      DrugRisk.caution => RiskStyle.of(RiskTone.caution, b),
      DrugRisk.safe => RiskStyle.of(RiskTone.safe, b),
      DrugRisk.unjudged => RiskStyle.of(RiskTone.unjudged, b),
      DrugRisk.none => null,
    };
    if (style == null) {
      return const SizedBox(width: 22, height: 22);
    }
    return Container(
      width: 22,
      height: 22,
      decoration: BoxDecoration(color: style.container, shape: BoxShape.circle),
      child: Icon(style.icon, size: 14, color: style.color),
    );
  }
}
