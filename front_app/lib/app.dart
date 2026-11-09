import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'core/theme/app_theme.dart';
import 'core/storage/token_storage.dart';
import 'features/auth/auth_provider.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/register_screen.dart';
import 'features/camera/camera_provider.dart';
import 'features/camera/camera_screen.dart';
import 'features/camera/ocr_result_screen.dart';
import 'features/home/home_provider.dart';
import 'features/home/home_screen.dart';
import 'features/profile/profile_provider.dart';
import 'features/profile/profile_screen.dart';
import 'features/search/search_provider.dart';
import 'features/search/search_screen.dart';

/// 웹에서 `push`로 연 화면(프로필·스캔·스캔 결과·회원가입)도 주소·브라우저 기록에 남게 한다. 이 옵션이 꺼져 있으면 폰 브라우저의
/// 뒤로가기가 그 화면을 닫지 않고 그 전 기록(앱 밖일 수도 있음)으로 가 버린다.
void configureRouter() {
  GoRouter.optionURLReflectsImperativeAPIs = true;
}

final _router = GoRouter(
  refreshListenable: TokenStorage.authNotifier,
  redirect: (context, state) async {
    final token = await TokenStorage.getAccessToken();
    final isLoggedIn = token != null;
    final loc = state.matchedLocation;
    final onAuthPage = loc == '/login' || loc == '/register';
    if (!isLoggedIn && !onAuthPage) return '/login';
    if (isLoggedIn && onAuthPage) return '/';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
    GoRoute(path: '/register', builder: (_, __) => const RegisterScreen()),
    GoRoute(path: '/camera', builder: (_, __) => const CameraScreen()),
    GoRoute(path: '/ocr-result', builder: (_, __) => const OcrResultScreen()),
    GoRoute(path: '/profile', builder: (_, __) => const ProfileScreen()),
    ShellRoute(
      builder: (context, state, child) => _MainShell(child: child),
      routes: [
        GoRoute(path: '/', builder: (_, __) => const HomeScreen()),
        GoRoute(path: '/search', builder: (_, __) => const SearchScreen()),
      ],
    ),
  ],
);

class App extends StatelessWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProvider(create: (_) => HomeProvider()),
        ChangeNotifierProvider(create: (_) => SearchProvider()),
        ChangeNotifierProvider(create: (_) => CameraProvider()),
        ChangeNotifierProvider(create: (_) => ProfileProvider()),
      ],
      child: MaterialApp.router(
        title: '굿메디슨',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: ThemeMode.system,
        routerConfig: _router,
      ),
    );
  }
}

class _MainShell extends StatelessWidget {
  final Widget child;
  const _MainShell({required this.child});

  @override
  Widget build(BuildContext context) {
    final loc = GoRouterState.of(context).matchedLocation;
    final selectedIndex = loc == '/search' ? 1 : 0;

    // 안드로이드 뒤로가기: 검색 탭에서는 앱이 종료되지 않고 내 약 탭으로 돌아간다(탭 이동은 `go`라 되돌아갈 기록이 없다).
    return PopScope(
      canPop: selectedIndex == 0,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop) context.go('/');
      },
      child: Scaffold(
        body: child,
        bottomNavigationBar: DecoratedBox(
          decoration: BoxDecoration(
            border: Border(
              top: BorderSide(color: Theme.of(context).dividerColor),
            ),
          ),
          child: NavigationBar(
            selectedIndex: selectedIndex,
            onDestinationSelected: (i) {
              switch (i) {
                case 0:
                  context.go('/');
                case 1:
                  context.go('/search');
                case 2:
                  context.push('/camera');
              }
            },
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.medication_outlined),
                selectedIcon: Icon(Icons.medication_rounded),
                label: '내 약',
              ),
              NavigationDestination(
                icon: Icon(Icons.search_rounded),
                selectedIcon: Icon(Icons.search_rounded),
                label: '검색',
              ),
              NavigationDestination(
                icon: Icon(Icons.photo_camera_outlined),
                selectedIcon: Icon(Icons.photo_camera_rounded),
                label: '스캔',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
