import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/api/api_client.dart';
import '../../core/models/analysis_models.dart';
import '../../core/models/medicine_box_models.dart';
import '../../core/notifications/fcm_service.dart';
import '../../core/theme/app_theme.dart';
import '../camera/camera_provider.dart';
import 'home_provider.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _expanded = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
        (_) => context.read<HomeProvider>().loadEntries());
    FcmService.initializeAndRegister();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer2<HomeProvider, CameraProvider>(
        builder: (context, home, cam, _) {
      if (cam.addDoneCount > 0) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          cam.resetAddDone();
          home.loadEntries();
        });
      }
      return Scaffold(
        appBar: AppBar(
          title: const Text('내 약'),
          actions: [
            IconButton(
              icon: const Icon(Icons.info_outline_rounded),
              tooltip: '정보',
              onPressed: () => _showAbout(context),
            ),
          ],
        ),
        body: Column(children: [
          if (cam.error != null)
            _StripBanner(
              text: cam.error!,
              icon: Icons.error_outline_rounded,
              tone: _StripTone.error,
              onClose: cam.clearError,
            ),
          if (cam.isAdding)
            const _StripBanner(
              text: '약품을 추가하는 중입니다…',
              tone: _StripTone.busy,
            ),
          Expanded(child: _buildBody(context, home)),
        ]),
      );
    });
  }

  Widget _buildBody(BuildContext context, HomeProvider home) {
    if (home.isLoading && home.entries.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (home.entries.isEmpty) {
      return _EmptyState(onSearch: () => context.go('/search'));
    }

    return Stack(children: [
      ListView(
        padding: kScreenPadding,
        children: [
          if (home.checkResult != null) ...[
            _InteractionBanner(result: home.checkResult!, entries: home.entries),
            Gap.v12,
          ],
          for (final entry in home.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _MedicineCard(
                entry: entry,
                risk: home.riskMap[entry.drug.id] ?? DrugRisk.none,
                isExpanded: _expanded.contains(entry.id),
                onToggle: () => setState(() {
                  _expanded.contains(entry.id)
                      ? _expanded.remove(entry.id)
                      : _expanded.add(entry.id);
                }),
                onDelete: () => home.deleteEntry(entry.id),
              ),
            ),
        ],
      ),
      if (home.error != null)
        Positioned(
          bottom: 16,
          left: 16,
          right: 16,
          child: _FloatingError(text: home.error!, onClose: home.clearError),
        ),
    ]);
  }

  void _showAbout(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final headStyle = TextStyle(
        fontWeight: FontWeight.w700, fontSize: 13, color: scheme.primary);
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

    showDialog<void>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: const Text('굿메디슨'),
        content: SizedBox(
          width: 320,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('버전 0.1.0', style: bodyStyle),
              const SizedBox(height: 18),
              Text('데이터 출처', style: headStyle),
              const SizedBox(height: 6),
              Text('식품의약품안전처 · 공공데이터포털', style: bodyStyle),
              bullet('의약품개요정보 (e약은요)'),
              bullet('의약품 제품 허가정보'),
              bullet('의약품 낱알식별 정보'),
              bullet('DUR 병용금기 · 효능군중복주의'),
              const SizedBox(height: 18),
              Text('안내', style: headStyle),
              const SizedBox(height: 6),
              bullet('병용 위험 정보는 참고용이며 의학적 진단·처방이 아닙니다.'),
              bullet('DUR에 등록되지 않은 상호작용은 표시되지 않을 수 있습니다.'),
              bullet('복약 전 반드시 의사·약사와 상담하세요.'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(),
            child: const Text('닫기'),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------

enum _StripTone { error, busy }

class _StripBanner extends StatelessWidget {
  final String text;
  final IconData? icon;
  final _StripTone tone;
  final VoidCallback? onClose;

  const _StripBanner(
      {required this.text, this.icon, required this.tone, this.onClose});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isErr = tone == _StripTone.error;
    return Container(
      width: double.infinity,
      color: isErr ? scheme.errorContainer : scheme.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(children: [
        if (tone == _StripTone.busy)
          const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2))
        else
          Icon(icon, size: 16, color: scheme.onErrorContainer),
        const SizedBox(width: 10),
        Expanded(
          child: Text(text,
              style: TextStyle(
                  fontSize: 13,
                  color:
                      isErr ? scheme.onErrorContainer : scheme.onSurfaceVariant)),
        ),
        if (onClose != null)
          TextButton(onPressed: onClose, child: const Text('닫기')),
      ]),
    );
  }
}

class _FloatingError extends StatelessWidget {
  final String text;
  final VoidCallback onClose;
  const _FloatingError({required this.text, required this.onClose});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      elevation: 3,
      borderRadius: BorderRadius.circular(12),
      color: scheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
        child: Row(children: [
          Expanded(
              child: Text(text,
                  style: TextStyle(color: scheme.onErrorContainer))),
          TextButton(onPressed: onClose, child: const Text('닫기')),
        ]),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final VoidCallback onSearch;
  const _EmptyState({required this.onSearch});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.medication_outlined,
              size: 56, color: scheme.onSurfaceVariant),
          Gap.v16,
          Text('등록된 약이 없습니다',
              style: Theme.of(context).textTheme.titleMedium),
          Gap.v4,
          Text('검색하거나 처방전을 스캔해 약을 추가하면\n병용 위험을 확인해 드립니다.',
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.onSurfaceVariant, height: 1.5)),
          Gap.v24,
          FilledButton.icon(
            onPressed: onSearch,
            icon: const Icon(Icons.search_rounded, size: 18),
            label: const Text('약품 검색'),
            style: FilledButton.styleFrom(
                minimumSize: const Size(180, 48)),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _InteractionBanner extends StatelessWidget {
  final QuickCheckResponse result;
  final List<MedicineBoxEntry> entries;
  const _InteractionBanner({required this.result, required this.entries});

  @override
  Widget build(BuildContext context) {
    final tone = RiskStyle.toneFromLevel(result.riskLevel) ?? RiskTone.safe;
    final style = RiskStyle.of(tone, Theme.of(context).brightness);
    final isSafe = tone == RiskTone.safe;

    final label = switch (tone) {
      RiskTone.critical => '병용금기 ${result.contraindicatedCount}건 발견',
      RiskTone.caution => '효능군 중복 ${result.duplicateEffectGroupCount}건',
      RiskTone.safe => '함께 복용해도 괜찮아요',
    };
    final subLabel = isSafe ? 'DUR 병용금기·효능군중복 기준' : '탭하여 상세 보기';

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
                child: _FindingCard(finding: f, drugsById: drugsById),
              ),
            Gap.v8,
            _AiGuideSection(findings: result.findings),
          ],
        ),
      ),
    );
  }
}

class _FindingCard extends StatelessWidget {
  final FindingItem finding;
  final Map<String, MedicineBoxDrug> drugsById;
  const _FindingCard({required this.finding, required this.drugsById});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final tone = finding.interactionType == 'duplicate_effect_group'
        ? RiskTone.caution
        : RiskTone.critical;
    final style = RiskStyle.of(tone, Theme.of(context).brightness);
    final reasonLabel = tone == RiskTone.caution ? '중복 사유' : '금기 사유';

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
            _Badge(text: style.label, color: style.color),
          ]),
          if (drug1?.efcyQesitm != null) ...[
            Gap.v8,
            _DrugEfcyLine(name: finding.drug1Name, efcy: drug1!.efcyQesitm!),
          ],
          if (drug2?.efcyQesitm != null) ...[
            Gap.v4,
            _DrugEfcyLine(name: finding.drug2Name, efcy: drug2!.efcyQesitm!),
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
            Text(finding.mechanism!,
                style: TextStyle(
                    fontSize: 12.5, color: scheme.onSurfaceVariant, height: 1.4)),
          ],
          if (finding.source == 'residual') ...[
            Gap.v4,
            Text('※ 품목 단위 참고 데이터',
                style: TextStyle(
                    fontSize: 10.5, color: scheme.onSurfaceVariant)),
          ],
        ]),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String text;
  final Color color;
  const _Badge({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(text,
          style: const TextStyle(
              color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w700)),
    );
  }
}

class _DrugEfcyLine extends StatelessWidget {
  final String name;
  final String efcy;
  const _DrugEfcyLine({required this.name, required this.efcy});

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

// ---------------------------------------------------------------------------

enum _GuideState { idle, loading, loaded, error }

class _AiGuideSection extends StatefulWidget {
  final List<FindingItem> findings;
  const _AiGuideSection({required this.findings});

  @override
  State<_AiGuideSection> createState() => _AiGuideSectionState();
}

class _AiGuideSectionState extends State<_AiGuideSection> {
  _GuideState _state = _GuideState.idle;
  AnalysisGuideResponse? _guide;
  String? _error;

  Set<String> get _drugIds => {
        for (final f in widget.findings) ...[f.drug1Id, f.drug2Id],
      };

  Future<void> _fetchGuide() async {
    setState(() => _state = _GuideState.loading);
    try {
      // 로컬 LLM 콜드스타트(모델을 GPU에 새로 올림)는 실측 87~153초 걸림 — 백엔드
      // OLLAMA_TIMEOUT_SECONDS(200초)보다 짧게 잡으면 백엔드가 성공하기 전에
      // 여기서 먼저 끊겨버리므로, 항상 그보다 여유있게 잡는다.
      final res = await ApiClient.dio.post(
        'analysis/guide',
        data: {'drug_ids': _drugIds.toList()},
        options: Options(receiveTimeout: const Duration(seconds: 220)),
      );
      setState(() {
        _guide = AnalysisGuideResponse.fromJson(res.data);
        _state = _GuideState.loaded;
      });
    } on DioException catch (e) {
      setState(() {
        _error = 'AI 설명을 불러오지 못했습니다 (${e.response?.statusCode ?? '연결 오류'})';
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
                  'AI가 설명을 생성하는 중입니다\n보통 10~20초, 서버를 처음 깨우면 최대 2~3분',
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
              ]),
        );
    }
  }
}

// ---------------------------------------------------------------------------

class _MedicineCard extends StatelessWidget {
  final MedicineBoxEntry entry;
  final DrugRisk risk;
  final bool isExpanded;
  final VoidCallback onToggle;
  final VoidCallback onDelete;

  const _MedicineCard({
    required this.entry,
    required this.risk,
    required this.isExpanded,
    required this.onToggle,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final drug = entry.drug;
    return Card(
      child: InkWell(
        onTap: onToggle,
        borderRadius: BorderRadius.circular(kRadius),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 6, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _RiskDot(risk: risk),
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
              secondChild: drug.efcyQesitm != null
                  ? Padding(
                      padding: const EdgeInsets.fromLTRB(24, 10, 8, 0),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Divider(height: 1),
                            const SizedBox(height: 8),
                            Text(drug.efcyQesitm!,
                                style: TextStyle(
                                    fontSize: 12.5,
                                    height: 1.45,
                                    color: scheme.onSurfaceVariant)),
                          ]))
                  : const SizedBox(width: double.infinity),
            ),
          ]),
        ),
      ),
    );
  }
}

class _RiskDot extends StatelessWidget {
  final DrugRisk risk;
  const _RiskDot({required this.risk});

  @override
  Widget build(BuildContext context) {
    final b = Theme.of(context).brightness;
    final (RiskStyle? style) = switch (risk) {
      DrugRisk.contraindicated => RiskStyle.of(RiskTone.critical, b),
      DrugRisk.caution => RiskStyle.of(RiskTone.caution, b),
      DrugRisk.safe => RiskStyle.of(RiskTone.safe, b),
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
