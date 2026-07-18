#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#include <sys/stat.h>

@interface CRAppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, strong) NSMenuItem *statusMenuItem;
@property(nonatomic, strong) NSMenuItem *musicMenuItem;
@property(nonatomic, strong) NSMenuItem *chimeMenuItem;
@property(nonatomic, strong) NSTimer *timer;
@property(nonatomic, strong) NSMutableDictionary *config;
@property(nonatomic, copy) NSString *runtimeToken;
@property(nonatomic) NSInteger runtimePort;
@end

@implementation CRAppDelegate

- (NSString *)homePath { return [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/Codex Rest"]; }
- (NSString *)configPath { return [[self homePath] stringByAppendingPathComponent:@"config.json"]; }
- (NSString *)runtimePath { return [[self homePath] stringByAppendingPathComponent:@"run/runtime.json"]; }
- (NSString *)wrapperPath { return [NSHomeDirectory() stringByAppendingPathComponent:@".local/bin/codex-rest"]; }
- (NSString *)hooksPath { return [NSHomeDirectory() stringByAppendingPathComponent:@".codex/hooks.json"]; }

- (NSMutableDictionary *)defaultConfig {
    return [@{
        @"music_enabled": @YES, @"completion_sound_enabled": @YES,
        @"music_volume": @0.30, @"completion_volume": @0.45,
        @"music_source": @"builtin", @"playlist_order": @"sequential", @"tracks": @[]
    } mutableCopy];
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [self buildStatusMenu];
    [self buildWindow];
    [self loadConfig];
    if (![self integrationIsInstalled]) [self installIntegration:nil];
    else [self startBackendAndLoad];
    self.timer = [NSTimer scheduledTimerWithTimeInterval:1.0 target:self selector:@selector(refreshStatus:) userInfo:nil repeats:YES];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return NO; }
- (void)applicationWillTerminate:(NSNotification *)notification { [self.timer invalidate]; }

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, 900, 720);
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                             styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                                                        NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable |
                                                        NSWindowStyleMaskFullSizeContentView)
                                               backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Codex Rest";
    self.window.minSize = NSMakeSize(760, 620);
    self.window.titlebarAppearsTransparent = YES;
    self.window.delegate = self;
    [self.window center];

    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = [WKWebsiteDataStore nonPersistentDataStore];
    self.webView = [[WKWebView alloc] initWithFrame:frame configuration:configuration];
    self.webView.navigationDelegate = self;
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.underPageBackgroundColor = [NSColor colorWithRed:0.12 green:0.08 blue:0.17 alpha:1.0];
    self.window.contentView = self.webView;
    NSString *placeholder = @"<!doctype html><meta charset='utf-8'><style>body{margin:0;background:linear-gradient(145deg,#21162d,#6e3546,#d17958);color:#fff4de;font-family:-apple-system;display:grid;place-items:center;height:100vh}main{text-align:center}h1{font-family:serif;font-weight:500;font-size:42px}p{opacity:.7}</style><main><h1>Codex Rest</h1><p>設定を読み込んでいます…</p></main>";
    [self.webView loadHTMLString:placeholder baseURL:nil];
}

- (void)buildStatusMenu {
    self.statusItem = [[NSStatusBar systemStatusBar] statusItemWithLength:NSSquareStatusItemLength];
    self.statusItem.button.image = [NSImage imageWithSystemSymbolName:@"cup.and.saucer" accessibilityDescription:@"Codex Rest"];
    self.statusItem.button.toolTip = @"Codex Rest — 待機中";
    NSMenu *menu = [NSMenu new];
    self.statusMenuItem = [[NSMenuItem alloc] initWithTitle:@"待機中です" action:@selector(showWindow:) keyEquivalent:@""];
    self.statusMenuItem.target = self;
    [menu addItem:self.statusMenuItem];
    [menu addItem:[NSMenuItem separatorItem]];
    self.musicMenuItem = [[NSMenuItem alloc] initWithTitle:@"音楽" action:@selector(toggleMusic:) keyEquivalent:@""];
    self.musicMenuItem.target = self;
    [menu addItem:self.musicMenuItem];
    self.chimeMenuItem = [[NSMenuItem alloc] initWithTitle:@"完了通知音" action:@selector(toggleChime:) keyEquivalent:@""];
    self.chimeMenuItem.target = self;
    [menu addItem:self.chimeMenuItem];
    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *show = [[NSMenuItem alloc] initWithTitle:@"設定を開く" action:@selector(showWindow:) keyEquivalent:@","];
    show.target = self; [menu addItem:show];
    NSMenuItem *install = [[NSMenuItem alloc] initWithTitle:@"Codex連携をインストール／更新" action:@selector(installIntegration:) keyEquivalent:@""];
    install.target = self; [menu addItem:install];
    NSMenuItem *instructions = [[NSMenuItem alloc] initWithTitle:@"/hooks の信頼手順をコピー" action:@selector(copyHookInstructions:) keyEquivalent:@""];
    instructions.target = self; [menu addItem:instructions];
    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"Codex Restを終了" action:@selector(terminate:) keyEquivalent:@"q"];
    quit.target = NSApp; [menu addItem:quit];
    self.statusItem.menu = menu;
}

- (void)loadConfig {
    NSMutableDictionary *merged = [self defaultConfig];
    NSData *data = [NSData dataWithContentsOfFile:[self configPath]];
    NSDictionary *loaded = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if ([loaded isKindOfClass:[NSDictionary class]]) [merged addEntriesFromDictionary:loaded];
    self.config = merged;
    self.musicMenuItem.state = [self.config[@"music_enabled"] boolValue] ? NSControlStateValueOn : NSControlStateValueOff;
    self.chimeMenuItem.state = [self.config[@"completion_sound_enabled"] boolValue] ? NSControlStateValueOn : NSControlStateValueOff;
}

- (void)saveConfig {
    NSString *directory = [[self configPath] stringByDeletingLastPathComponent];
    [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
    NSData *data = [NSJSONSerialization dataWithJSONObject:self.config options:NSJSONWritingPrettyPrinted error:nil];
    if ([data writeToFile:[self configPath] options:NSDataWritingAtomic error:nil]) chmod([[self configPath] fileSystemRepresentation], 0600);
}

- (BOOL)integrationIsInstalled {
    BOOL wrapper = [[NSFileManager defaultManager] isExecutableFileAtPath:[self wrapperPath]];
    NSString *runtimeCLIPath = [[self homePath] stringByAppendingPathComponent:@"runtime/codex_rest/cli.py"];
    NSString *runtimeCLI = [NSString stringWithContentsOfFile:runtimeCLIPath encoding:NSUTF8StringEncoding error:nil];
    BOOL supportsDesktopApp = [runtimeCLI containsString:@"def command_start"];
    NSString *hooks = [NSString stringWithContentsOfFile:[self hooksPath] encoding:NSUTF8StringEncoding error:nil];
    NSString *command = [[self wrapperPath] stringByAppendingString:@" hook"];
    NSUInteger count = 0;
    NSRange search = NSMakeRange(0, hooks.length);
    while (hooks && search.location < hooks.length) {
        NSRange found = [hooks rangeOfString:command options:0 range:search];
        if (found.location == NSNotFound) break;
        count++;
        NSUInteger next = NSMaxRange(found);
        search = NSMakeRange(next, hooks.length - next);
    }
    return wrapper && count == 4 && supportsDesktopApp;
}

- (BOOL)runTask:(NSString *)executable arguments:(NSArray<NSString *> *)arguments currentDirectory:(NSString *)directory {
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:executable];
    task.arguments = arguments;
    if (directory) task.currentDirectoryURL = [NSURL fileURLWithPath:directory];
    task.standardOutput = [NSPipe pipe]; task.standardError = [NSPipe pipe];
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) { [self showError:[NSString stringWithFormat:@"起動できませんでした: %@", error.localizedDescription]]; return NO; }
    [task waitUntilExit];
    return task.terminationStatus == 0;
}

- (void)installIntegration:(id)sender {
    NSString *backend = [[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:@"backend"];
    NSString *installer = [backend stringByAppendingPathComponent:@"install.py"];
    if (![[NSFileManager defaultManager] fileExistsAtPath:installer]) { [self showError:@"アプリ内のCodex連携インストーラーが見つかりません。"]; return; }
    if ([self runTask:@"/usr/bin/python3" arguments:@[installer] currentDirectory:backend]) {
        [self loadConfig]; [self startBackendAndLoad];
        if (sender) {
            NSAlert *alert = [NSAlert new];
            alert.messageText = @"Codex連携を更新しました";
            alert.informativeText = @"Codexを再起動し、/hooks でCodex Restの4件を信頼してください。";
            [alert addButtonWithTitle:@"OK"];
            [alert beginSheetModalForWindow:self.window completionHandler:nil];
        }
    } else [self showError:@"Codex連携をインストールできませんでした。"];
}

- (void)startBackendAndLoad {
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:[self wrapperPath]]) return;
    [self runTask:[self wrapperPath] arguments:@[@"start"] currentDirectory:nil];
    [self loadRuntimeWithRetry:0];
}

- (void)loadRuntimeWithRetry:(NSInteger)attempt {
    NSData *data = [NSData dataWithContentsOfFile:[self runtimePath]];
    NSDictionary *runtime = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    NSNumber *port = runtime[@"port"]; NSString *token = runtime[@"token"];
    if (port && token) {
        self.runtimePort = port.integerValue; self.runtimeToken = token;
        NSString *address = [NSString stringWithFormat:@"http://127.0.0.1:%ld/settings#%@", (long)self.runtimePort, self.runtimeToken];
        [self.webView loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:address]]];
        return;
    }
    if (attempt < 20) dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.15 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{ [self loadRuntimeWithRetry:attempt + 1]; });
    else [self showError:@"Codex Restバックエンドを起動できませんでした。"];
}

- (void)refreshStatus:(NSTimer *)timer {
    [self loadConfig];
    NSData *runtimeData = [NSData dataWithContentsOfFile:[self runtimePath]];
    NSDictionary *runtime = runtimeData ? [NSJSONSerialization JSONObjectWithData:runtimeData options:0 error:nil] : nil;
    NSNumber *port = runtime[@"port"]; NSString *token = runtime[@"token"];
    if (!port || !token) { [self applyActiveCount:0 pausedCount:0 online:NO]; return; }
    NSURL *url = [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%@/api/state", port]];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    [request setValue:token forHTTPHeaderField:@"X-Codex-Rest-Token"];
    NSURLSessionDataTask *task = [[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *payload, NSURLResponse *response, NSError *error) {
        NSDictionary *state = payload ? [NSJSONSerialization JSONObjectWithData:payload options:0 error:nil] : nil;
        NSInteger active = [state[@"active_count"] integerValue]; NSInteger paused = [state[@"paused_count"] integerValue];
        dispatch_async(dispatch_get_main_queue(), ^{ [self applyActiveCount:active pausedCount:paused online:(state != nil && error == nil)]; });
    }];
    [task resume];
}

- (void)applyActiveCount:(NSInteger)active pausedCount:(NSInteger)paused online:(BOOL)online {
    NSString *title; NSString *symbol;
    if (paused > 0) { title = @"人間の操作を待っています"; symbol = @"hand.raised.fill"; }
    else if (active > 0) { title = [NSString stringWithFormat:@"Codexが作業中です（%ld件）", (long)active]; symbol = @"cup.and.saucer.fill"; }
    else { title = online ? @"待機中です" : @"バックエンド停止中"; symbol = online ? @"cup.and.saucer" : @"exclamationmark.circle"; }
    self.statusMenuItem.title = title;
    self.statusItem.button.image = [NSImage imageWithSystemSymbolName:symbol accessibilityDescription:title];
    self.statusItem.button.toolTip = [@"Codex Rest — " stringByAppendingString:title];
}

- (void)toggleMusic:(id)sender {
    self.config[@"music_enabled"] = @(![self.config[@"music_enabled"] boolValue]);
    [self saveConfig]; [self loadConfig]; [self.webView reload];
}
- (void)toggleChime:(id)sender {
    self.config[@"completion_sound_enabled"] = @(![self.config[@"completion_sound_enabled"] boolValue]);
    [self saveConfig]; [self loadConfig]; [self.webView reload];
}
- (void)showWindow:(id)sender { [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES]; }

- (void)copyHookInstructions:(id)sender {
    NSString *text = @"/Applications/ChatGPT.app/Contents/Resources/codex\n起動後に /hooks を入力し、Codex Restの4件を信頼してください。";
    [[NSPasteboard generalPasteboard] clearContents];
    [[NSPasteboard generalPasteboard] setString:text forType:NSPasteboardTypeString];
    NSAlert *alert = [NSAlert new]; alert.messageText = @"信頼手順をコピーしました"; alert.informativeText = text; [alert addButtonWithTitle:@"OK"];
    [alert beginSheetModalForWindow:self.window completionHandler:nil];
}

- (void)showError:(NSString *)message {
    NSAlert *alert = [NSAlert new]; alert.alertStyle = NSAlertStyleCritical; alert.messageText = @"Codex Rest"; alert.informativeText = message; [alert addButtonWithTitle:@"OK"];
    if (self.window) [alert beginSheetModalForWindow:self.window completionHandler:nil]; else [alert runModal];
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        CRAppDelegate *delegate = [CRAppDelegate new];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
