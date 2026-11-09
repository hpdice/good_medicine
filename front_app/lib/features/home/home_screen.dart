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
import 'widgets/source_notes.dart';
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
              tooltip: '내 정보(건강 상태·출생연도·임신 여부)',
              // 프로필(건강 상태·출생연도·임신 여부)이 바뀌면 판정이 달라지므로, 돌아올 때 다시 불러온다.
              onPressed: () async {
                await context.push('/profile');
                if (context.mounted) context.read<HomeProvider>().loadEntries();
              },
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
    showDialog<void>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: const Text('굿메디슨'),
        content: const SizedBox(
          width: 320,
          child: SingleChildScrollView(child: SourceNotes()),
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
