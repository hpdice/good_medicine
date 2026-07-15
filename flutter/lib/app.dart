import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'core/storage/token_storage.dart';
import 'features/auth/auth_provider.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/register_screen.dart';
import 'features/camera/camera_provider.dart';
import 'features/camera/camera_screen.dart';
import 'features/camera/ocr_result_screen.dart';
import 'features/home/home_provider.dart';
import 'features/home/home_screen.dart';
import 'features/search/search_provider.dart';
import 'features/search/search_screen.dart';

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
      ],
      child: MaterialApp.router(
        title: '약봉투',
        theme: ThemeData(
          colorScheme:
              ColorScheme.fromSeed(seedColor: const Color(0xFF4CAF50)),
          useMaterial3: true,
        ),
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

    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
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
          NavigationDestination(icon: Icon(Icons.home_outlined), label: '홈'),
          NavigationDestination(icon: Icon(Icons.search), label: '검색'),
          NavigationDestination(
              icon: Icon(Icons.camera_alt_outlined), label: '스캔'),
        ],
      ),
    );
  }
}
