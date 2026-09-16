import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/models/medicine_box_models.dart';
import '../../core/notifications/fcm_service.dart';
import '../../core/theme/app_theme.dart';
import '../camera/camera_provider.dart';
import 'home_provider.dart';
import 'widgets/empty_state.dart';
import 'widgets/floating_error.dart';
import 'widgets/interaction_banner.dart';
import 'widgets/medicine_card.dart';
import 'widgets/reminder_edit_sheet.dart';
import 'widgets/strip_banner.dart';

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
              icon: const Icon(Icons.person_outline_rounded),
              tooltip: '내 정보(건강정보·알레르기)',
              onPressed: () => context.push('/profile'),
            ),
            IconButton(
              icon: const Icon(Icons.info_outline_rounded),
              tooltip: '정보',
              onPressed: () => _showAbout(context),
            ),
          ],
        ),
        body: Column(children: [
          if (cam.error != null)
            StripBanner(
              text: cam.error!,
              icon: Icons.error_outline_rounded,
              tone: StripTone.error,
              onClose: cam.clearError,
            ),
          if (cam.isAdding)
            const StripBanner(
              text: '약품을 추가하는 중입니다…',
              tone: StripTone.busy,
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
      return EmptyState(onSearch: () => context.go('/search'));
    }

    return Stack(children: [
      ListView(
        padding: kScreenPadding,
        children: [
          if (home.checkResult != null) ...[
            InteractionBanner(result: home.checkResult!, entries: home.entries),
            Gap.v12,
          ],
          for (final entry in home.entries)
            Padding(
              key: ValueKey(entry.id),
              padding: const EdgeInsets.only(bottom: 10),
              child: MedicineCard(
                entry: entry,
                risk: home.riskMap[entry.drug.id] ?? DrugRisk.none,
                isExpanded: _expanded.contains(entry.id),
                onToggle: () => setState(() {
                  _expanded.contains(entry.id)
                      ? _expanded.remove(entry.id)
                      : _expanded.add(entry.id);
                }),
                onDelete: () => _confirmDelete(context, home, entry),
                onEditReminder: () => showReminderEditSheet(context, entry),
              ),
            ),
        ],
      ),
      if (home.error != null)
        Positioned(
          bottom: 16,
          left: 16,
          right: 16,
          child: FloatingError(text: home.error!, onClose: home.clearError),
        ),
    ]);
  }

  Future<void> _confirmDelete(
      BuildContext context, HomeProvider home, MedicineBoxEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: const Text('약 삭제'),
        content: Text('${entry.drug.displayName}을(를) 복약함에서 삭제할까요?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            child: Text('삭제',
                style: TextStyle(color: Theme.of(dialogCtx).colorScheme.error)),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      home.deleteEntry(entry.id);
    }
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
