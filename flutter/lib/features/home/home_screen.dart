import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../core/api/api_client.dart';
import '../../core/models/analysis_models.dart';
import '../../core/models/medicine_box_models.dart';
import '../../core/notifications/fcm_service.dart';
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
        appBar: AppBar(title: const Text('내 약 목록')),
        body: Column(children: [
          if (cam.error != null)
            Container(
              width: double.infinity,
              color: Theme.of(context).colorScheme.errorContainer,
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(children: [
                Icon(Icons.error_outline,
                    size: 16,
                    color: Theme.of(context).colorScheme.onErrorContainer),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(cam.error!,
                      style: TextStyle(
                          fontSize: 13,
                          color: Theme.of(context).colorScheme.onErrorContainer)),
                ),
                TextButton(
                    onPressed: cam.clearError, child: const Text('닫기')),
              ]),
            ),
          if (cam.isAdding)
            Container(
              width: double.infinity,
              color: Colors.orange.shade50,
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(children: [
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 10),
                Text('약품을 추가하는 중입니다...',
                    style: TextStyle(
                        fontSize: 13, color: Colors.orange.shade800)),
              ]),
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
      return const Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('등록된 약이 없습니다.'),
          SizedBox(height: 8),
          Text('검색이나 카메라로 약을 추가해 보세요.',
              style: TextStyle(color: Colors.grey)),
        ]),
      );
    }

    return Stack(children: [
      ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (home.checkResult != null)
            _InteractionBanner(result: home.checkResult!, entries: home.entries),
          if (home.checkResult != null) const SizedBox(height: 8),
          ...home.entries.map((entry) {
            final risk = home.riskMap[entry.drug.id] ?? DrugRisk.none;
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _MedicineCard(
                entry: entry,
                risk: risk,
                isExpanded: _expanded.contains(entry.id),
                onToggle: () => setState(() {
                  _expanded.contains(entry.id)
                      ? _expanded.remove(entry.id)
                      : _expanded.add(entry.id);
                }),
                onDelete: () => home.deleteEntry(entry.id),
              ),
            );
          }),
        ],
      ),
      if (home.error != null)
        Positioned(
          bottom: 16,
          left: 16,
          right: 16,
          child: Material(
            elevation: 4,
            borderRadius: BorderRadius.circular(8),
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Row(children: [
                Expanded(
                    child: Text(home.error!,
                        style: TextStyle(
                            color: Theme.of(context)
                                .colorScheme
                                .onErrorContainer))),
                TextButton(
                    onPressed: home.clearError, child: const Text('닫기')),
              ]),
            ),
          ),
        ),
    ]);
  }
}

class _InteractionBanner extends StatelessWidget {
  final QuickCheckResponse result;
  final List<MedicineBoxEntry> entries;
  const _InteractionBanner({required this.result, required this.entries});

  @override
  Widget build(BuildContext context) {
    final level = result.riskLevel;
    final isSafe = level == 'safe';

    final Color bgColor;
    final String label;
    final IconData icon;
    switch (level) {
      case 'critical':
        bgColor = const Color(0xFFB71C1C);
        label = '병용금기 ${result.contraindicatedCount}건';
        icon = Icons.warning_amber_rounded;
      case 'caution':
        bgColor = const Color(0xFFEF6C00);
        label = '효능군 중복 ${result.duplicateEffectGroupCount}건';
        icon = Icons.info_outline;
      default:
        bgColor = const Color(0xFF4CAF50);
        label = '안전 — 상호작용 없음';
        icon = Icons.check_circle;
    }

    return GestureDetector(
      onTap: isSafe ? null : () => _showFindings(context, result, entries),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration:
            BoxDecoration(color: bgColor, borderRadius: BorderRadius.circular(12)),
        child: Row(children: [
          Icon(icon, color: Colors.white),
          const SizedBox(width: 8),
          Expanded(
              child: Text(label,
                  style: const TextStyle(
                      color: Colors.white, fontWeight: FontWeight.w600))),
          if (!isSafe)
            const Icon(Icons.chevron_right, color: Colors.white),
        ]),
      ),
    );
  }

  void _showFindings(
      BuildContext context, QuickCheckResponse result, List<MedicineBoxEntry> entries) {
    final drugsById = {for (final e in entries) e.drug.id: e.drug};
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.5,
        builder: (_, ctrl) => ListView(
          controller: ctrl,
          padding: const EdgeInsets.all(16),
          children: [
            Text('상호작용 상세',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            ...result.findings
                .map((f) => _FindingCard(finding: f, drugsById: drugsById)),
            const SizedBox(height: 8),
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
    final (badgeColor, badgeLabel, reasonLabel) = switch (finding.interactionType) {
      'duplicate_effect_group' => (
          const Color(0xFFEF6C00),
          '효능군 중복',
          '중복 사유:',
        ),
      _ => (
          const Color(0xFFF44336),
          '병용 금기',
          '금기 사유:',
        ),
    };

    final drug1 = drugsById[finding.drug1Id];
    final drug2 = drugsById[finding.drug2Id];

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${finding.drug1Name} × ${finding.drug2Name}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                  color: badgeColor,
                  borderRadius: BorderRadius.circular(4)),
              child: Text(badgeLabel,
                  style: const TextStyle(color: Colors.white, fontSize: 12)),
            ),
          ]),
          if (drug1?.efcyQesitm != null) ...[
            const SizedBox(height: 6),
            _DrugEfcyLine(name: finding.drug1Name, efcy: drug1!.efcyQesitm!),
          ],
          if (drug2?.efcyQesitm != null) ...[
            const SizedBox(height: 4),
            _DrugEfcyLine(name: finding.drug2Name, efcy: drug2!.efcyQesitm!),
          ],
          if (finding.mechanism != null) ...[
            const SizedBox(height: 6),
            Text(reasonLabel,
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.error)),
            Text(finding.mechanism!,
                style:
                    TextStyle(fontSize: 12, color: Colors.grey.shade700)),
          ],
        ]),
      ),
    );
  }
}

class _DrugEfcyLine extends StatelessWidget {
  final String name;
  final String efcy;
  const _DrugEfcyLine({required this.name, required this.efcy});

  @override
  Widget build(BuildContext context) {
    return RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
        children: [
          TextSpan(
              text: '$name: ',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          TextSpan(text: efcy),
        ],
      ),
    );
  }
}

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
    switch (_state) {
      case _GuideState.idle:
        return OutlinedButton.icon(
          onPressed: _fetchGuide,
          icon: const Icon(Icons.auto_awesome, size: 18),
          label: const Text('AI 설명 보기'),
        );
      case _GuideState.loading:
        return const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Row(children: [
            SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 10),
            Expanded(
                child: Text(
                    'AI가 설명을 생성하는 중입니다... (보통 10~20초, 서버를 처음 깨우는 경우 최대 2~3분까지 걸릴 수 있어요)')),
          ]),
        );
      case _GuideState.error:
        return Row(children: [
          Expanded(
              child: Text(_error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error))),
          TextButton(onPressed: _fetchGuide, child: const Text('다시 시도')),
        ]);
      case _GuideState.loaded:
        final guide = _guide!;
        return Card(
          color: Colors.blue.shade50,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Icon(Icons.auto_awesome, size: 16, color: Colors.blueGrey),
                const SizedBox(width: 6),
                Text(guide.isAiGenerated ? 'AI 참고용 설명' : '안내',
                    style:
                        const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
              ]),
              const SizedBox(height: 8),
              Text(guide.guideText, style: const TextStyle(fontSize: 13, height: 1.4)),
              if (guide.disclaimer.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(guide.disclaimer,
                    style: TextStyle(
                        fontSize: 11,
                        color: Colors.grey.shade600,
                        fontStyle: FontStyle.italic)),
              ],
            ]),
          ),
        );
    }
  }
}

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
    final drug = entry.drug;
    return Card(
      child: InkWell(
        onTap: onToggle,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _RiskIcon(risk: risk),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(drug.displayName,
                          style: const TextStyle(fontWeight: FontWeight.w500)),
                      if (drug.className != null)
                        Text(drug.className!,
                            style: TextStyle(
                                fontSize: 12, color: Colors.grey.shade600)),
                      if (drug.efcyQesitm != null && !isExpanded)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(drug.efcyQesitm!,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                  fontSize: 12, color: Colors.grey.shade700)),
                        ),
                    ]),
              ),
              if (drug.etcOtcName != null)
                Chip(
                    label: Text(drug.etcOtcName!,
                        style: const TextStyle(fontSize: 11)),
                    padding: EdgeInsets.zero,
                    visualDensity: VisualDensity.compact),
              IconButton(
                icon: Icon(Icons.delete_outline,
                    color: Theme.of(context).colorScheme.error),
                onPressed: onDelete,
              ),
            ]),
            AnimatedCrossFade(
              duration: const Duration(milliseconds: 200),
              crossFadeState: isExpanded
                  ? CrossFadeState.showSecond
                  : CrossFadeState.showFirst,
              firstChild: const SizedBox.shrink(),
              secondChild: drug.efcyQesitm != null
                  ? Padding(
                      padding: const EdgeInsets.only(top: 8, left: 12),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Divider(),
                            const SizedBox(height: 4),
                            Text(drug.efcyQesitm!,
                                style: TextStyle(
                                    fontSize: 12, color: Colors.grey.shade700)),
                          ]))
                  : const SizedBox.shrink(),
            ),
          ]),
        ),
      ),
    );
  }
}

class _RiskIcon extends StatelessWidget {
  final DrugRisk risk;
  const _RiskIcon({required this.risk});

  @override
  Widget build(BuildContext context) {
    return switch (risk) {
      DrugRisk.contraindicated => const Icon(Icons.warning_amber_rounded,
          color: Color(0xFFF44336), size: 24),
      DrugRisk.caution =>
        const Icon(Icons.info_outline, color: Color(0xFFEF6C00), size: 24),
      DrugRisk.safe =>
        const Icon(Icons.check_circle, color: Color(0xFF4CAF50), size: 24),
      DrugRisk.none => const SizedBox(width: 24, height: 24),
    };
  }
}
