"""Janela do app no Mac: janela própria com WebKit (como a versão 4), sem barra de título do sistema.

O desenho da janela (cinza escuro, cantos arredondados, borda branca fina, sombra azul clara) é feito pela
própria tela (HTML); a janela do Mac é transparente. Uma faixa invisível no topo deixa arrastar a janela.

- Arrastar arquivos para o ícone no Dock ou para a janela: entram na lista.
- ⌘Q / ⌘W / bolinha vermelha: se houver envio ou transcrição em andamento, a tela pergunta antes.
- Enquanto envia ou transcreve, o Mac não dorme (caffeinate).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import objc
from AppKit import (NSApp, NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
                    NSBitmapImageRep, NSColor, NSDragOperationCopy, NSDragOperationNone, NSMakeRect, NSMenu,
                    NSMenuItem, NSOpenPanel, NSPasteboardTypeFileURL, NSView, NSWindow,
                    NSWindowStyleMaskBorderless, NSWindowStyleMaskMiniaturizable)
from Foundation import NSURL, NSObject
from PyObjCTools import AppHelper
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

from . import __version__
from .app import App, Bridge, log

W, H = 600, 680                 # janela (a "janela desenhada" fica 20 px para dentro, por causa da sombra)
UI = Path(__file__).resolve().parent / "ui" / "index.html"
NSTerminateCancel, NSTerminateNow = 0, 1
NSWindowAbove = 1
NSPasteboardURLReadingFileURLsOnlyKey = "NSPasteboardURLReadingFileURLsOnlyKey"

WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")


# ------------------------------------------------------------------ peças da janela

class KeyWindow(NSWindow):
    """Janela sem borda que aceita teclado (para digitar no campo do link)."""
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class DragStrip(NSView):
    """Faixa invisível no topo: arrasta a janela."""
    def mouseDownCanMoveWindow(self):
        return True

    def mouseDown_(self, event):
        try:
            self.window().performWindowDragWithEvent_(event)
        except Exception:
            pass


class DropWebView(WKWebView):
    """WebKit que recebe arquivos arrastados do Finder (e não tenta abrir o vídeo dentro da janela)."""
    shell = None

    @objc.python_method
    def _paths(self, info):
        pb = info.draggingPasteboard()
        urls = pb.readObjectsForClasses_options_([NSURL], {NSPasteboardURLReadingFileURLsOnlyKey: True}) or []
        return [str(u.path()) for u in urls if u.isFileURL()]

    def draggingEntered_(self, info):
        if self._paths(info):
            if self.shell:
                self.shell.send({"type": "drag", "on": True})
            return NSDragOperationCopy
        return NSDragOperationNone

    def draggingUpdated_(self, info):
        return NSDragOperationCopy if self._paths(info) else NSDragOperationNone

    def draggingExited_(self, info):
        if self.shell:
            self.shell.send({"type": "drag", "on": False})

    def prepareForDragOperation_(self, info):
        return True

    def performDragOperation_(self, info):
        paths = self._paths(info)
        if self.shell:
            self.shell.send({"type": "drag", "on": False})
            if paths:
                threading.Thread(target=self.shell.app.add_files, args=(paths,), daemon=True).start()
        return bool(paths)

    def concludeDragOperation_(self, info):
        pass


class MessageHandler(NSObject, protocols=[WKScriptMessageHandler]):
    shell = None

    def userContentController_didReceiveScriptMessage_(self, ucc, message):
        try:
            msg = json.loads(str(message.body()))
        except Exception:
            return
        if self.shell:
            self.shell.app.handle(msg)


# ------------------------------------------------------------------ o app

class Shell(Bridge):
    def __init__(self, files: list[str], snapshot: str | None = None):
        self.app = App(self)
        self.window = None
        self.web = None
        self.ready = False
        self.force_quit = False
        self.caff = None
        self.snapshot = snapshot
        if files:
            self.app.add_files(files)

    # -------- ponte (Python → tela)
    def send(self, msg: dict) -> None:
        js = "app.recv(" + json.dumps(json.dumps(msg, ensure_ascii=False)) + ")"
        AppHelper.callAfter(self._eval, js)

    def _eval(self, js: str) -> None:
        if self.web is not None:
            self.web.evaluateJavaScript_completionHandler_(js, None)

    # -------- janelas do sistema
    def pick_files(self) -> list[str]:
        p = NSOpenPanel.openPanel()
        p.setCanChooseFiles_(True)
        p.setCanChooseDirectories_(True)
        p.setAllowsMultipleSelection_(True)
        p.setMessage_("Escolha os vídeos (ou pastas) para subir")
        p.setPrompt_("Escolher")
        if p.runModal() == 1:
            return [str(u.path()) for u in p.URLs()]
        return []

    def pick_rclone(self) -> str | None:
        p = NSOpenPanel.openPanel()
        p.setCanChooseFiles_(True)
        p.setCanChooseDirectories_(False)
        p.setAllowsMultipleSelection_(False)
        p.setMessage_("Aponte o programa rclone (no setor: pasta Aplicativos › rclone, dentro da sua pasta pessoal)")
        p.setPrompt_("Usar este")
        p.setTreatsFilePackagesAsDirectories_(True)
        d = Path.home() / "Applications" / "rclone"
        if d.is_dir():
            p.setDirectoryURL_(NSURL.fileURLWithPath_(str(d)))
        if p.runModal() == 1 and p.URLs():
            return str(p.URLs()[0].path())
        return None

    def open_url(self, url: str) -> None:
        subprocess.Popen(["open", url])

    def open_file(self, path: str) -> None:
        subprocess.Popen(["open", path])

    def quit(self) -> None:
        self.force_quit = True
        AppHelper.callAfter(NSApp().terminate_, None)

    def minimize(self) -> None:
        AppHelper.callAfter(self.window.miniaturize_, None)

    def busy_changed(self, busy: bool) -> None:
        """Enquanto envia ou transcreve, o Mac não dorme."""
        if busy and self.caff is None:
            try:
                self.caff = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            except OSError:
                self.caff = None
        elif not busy and self.caff is not None:
            try:
                self.caff.terminate()
            except Exception:
                pass
            self.caff = None

    # -------- montar a janela
    def build(self) -> None:
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskMiniaturizable
        win = KeyWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(False)
        win.setTitle_("Subir no Drive")
        win.setReleasedWhenClosed_(False)
        win.center()

        cfg = WKWebViewConfiguration.alloc().init()
        ucc = WKUserContentController.alloc().init()
        handler = MessageHandler.alloc().init()
        handler.shell = self
        ucc.addScriptMessageHandler_name_(handler, "app")
        cfg.setUserContentController_(ucc)
        web = DropWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, W, H), cfg)
        web.shell = self
        try:
            web.setValue_forKey_(False, "drawsBackground")
        except Exception:
            pass
        web.registerForDraggedTypes_([NSPasteboardTypeFileURL])
        web.setAutoresizingMask_(18)
        cv = win.contentView()
        cv.addSubview_(web)
        # faixa para arrastar: barra de título desenhada (20 px de margem + ~46 px), fora das bolinhas
        strip = DragStrip.alloc().initWithFrame_(NSMakeRect(110, H - 20 - 46, W - 110 - 24, 46))
        cv.addSubview_positioned_relativeTo_(strip, NSWindowAbove, web)
        web.loadFileURL_allowingReadAccessToURL_(NSURL.fileURLWithPath_(str(UI)),
                                                 NSURL.fileURLWithPath_(str(UI.parent)))
        self.window, self.web, self._handler = win, web, handler
        win.makeKeyAndOrderFront_(None)
        NSApp().activateIgnoringOtherApps_(True)
        if self.snapshot:
            threading.Thread(target=self._snapshot_run, daemon=True).start()

    def show(self) -> None:
        if self.window is not None:
            self.window.makeKeyAndOrderFront_(None)
            NSApp().activateIgnoringOtherApps_(True)

    # -------- foto da janela (teste na montagem do GitHub)
    def _snap(self, path: str) -> None:
        done = threading.Event()

        def take():
            def handler(img, err):
                try:
                    if img is not None:
                        rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
                        data = rep.representationUsingType_properties_(4, {})   # PNG
                        data.writeToFile_atomically_(path, True)
                        log(f"foto: {path}")
                    else:
                        log(f"foto falhou: {err}")
                finally:
                    done.set()
            self.web.takeSnapshotWithConfiguration_completionHandler_(None, handler)
        AppHelper.callAfter(take)
        done.wait(20)

    def _js(self, code: str) -> None:
        AppHelper.callAfter(self._eval, code)

    def _snapshot_run(self) -> None:
        """Roteiro do teste: tela de escolher pasta → enviando → fim. Fotos em PNG na pasta pedida."""
        out = Path(self.snapshot)
        out.mkdir(parents=True, exist_ok=True)
        time.sleep(4)
        self._snap(str(out / "1-escolher.png"))
        target = os.environ.get("SUBIR_TEST_OPEN")      # pasta para entrar antes de subir (ex.: "26_701 Maria/2026 11 10/Saída")
        if target:
            for part in target.split("/"):
                self._js(f"openDir({json.dumps(part)})")
                time.sleep(1.5)
            self._snap(str(out / "2-pasta-saida.png"))
        if os.environ.get("SUBIR_TEST_UPLOAD"):
            self._js("upload()")
            time.sleep(float(os.environ.get("SUBIR_TEST_MID", "6")))
            self._snap(str(out / "3-enviando.png"))
            t0 = time.time()
            while time.time() - t0 < float(os.environ.get("SUBIR_TEST_TIMEOUT", "600")):
                if not self.app.busy():
                    break
                time.sleep(1)
            time.sleep(2)
            self._snap(str(out / "4-fim.png"))
            v = self.app.job_view() or {}
            (out / "resultado.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
        self.quit()


class AppDelegate(NSObject):
    shell = None

    def applicationDidFinishLaunching_(self, note):
        self.shell.build()

    def application_openFiles_(self, sender, filenames):
        paths = [str(f) for f in filenames]
        log(f"arquivos recebidos pelo ícone: {len(paths)}")
        threading.Thread(target=self.shell.app.add_files, args=(paths,), daemon=True).start()
        self.shell.show()
        sender.replyToOpenOrPrint_(0)          # NSApplicationDelegateReplySuccess

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
        self.shell.show()
        return True

    def applicationShouldTerminate_(self, sender):
        if self.shell.force_quit or not self.shell.app.busy():
            return NSTerminateNow
        self.shell.show()
        self.shell.send({"type": "ask_close"})
        return NSTerminateCancel

    def applicationWillTerminate_(self, note):
        try:
            if self.shell.app.job and self.shell.app.job.busy:
                self.shell.app.job.cancel()
                self.shell.app.job.wait(5)
            if self.shell.app.job:
                self.shell.app.job.cleanup()
        except Exception:
            pass
        self.shell.busy_changed(False)

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return True

    def askClose_(self, sender):
        self.shell.show()
        self.shell.send({"type": "ask_close"})

    def minimize_(self, sender):
        if self.shell.window is not None:
            self.shell.window.miniaturize_(None)


def _menu(delegate) -> NSMenu:
    bar = NSMenu.alloc().init()
    # menu do app
    item = NSMenuItem.alloc().init()
    bar.addItem_(item)
    m = NSMenu.alloc().initWithTitle_("Subir no Drive")
    m.addItemWithTitle_action_keyEquivalent_(f"Subir no Drive {__version__}", None, "")
    m.addItem_(NSMenuItem.separatorItem())
    m.addItemWithTitle_action_keyEquivalent_("Ocultar", "hide:", "h")
    q = m.addItemWithTitle_action_keyEquivalent_("Sair do Subir no Drive", "terminate:", "q")
    q.setTarget_(NSApp())
    item.setSubmenu_(m)
    # Editar (copiar e colar o link)
    item = NSMenuItem.alloc().init()
    bar.addItem_(item)
    m = NSMenu.alloc().initWithTitle_("Editar")
    m.addItemWithTitle_action_keyEquivalent_("Desfazer", "undo:", "z")
    m.addItem_(NSMenuItem.separatorItem())
    m.addItemWithTitle_action_keyEquivalent_("Recortar", "cut:", "x")
    m.addItemWithTitle_action_keyEquivalent_("Copiar", "copy:", "c")
    m.addItemWithTitle_action_keyEquivalent_("Colar", "paste:", "v")
    m.addItemWithTitle_action_keyEquivalent_("Selecionar tudo", "selectAll:", "a")
    item.setSubmenu_(m)
    # Janela
    item = NSMenuItem.alloc().init()
    bar.addItem_(item)
    m = NSMenu.alloc().initWithTitle_("Janela")
    mi = m.addItemWithTitle_action_keyEquivalent_("Minimizar", "minimize:", "m")
    mi.setTarget_(delegate)
    mi = m.addItemWithTitle_action_keyEquivalent_("Fechar", "askClose:", "w")
    mi.setTarget_(delegate)
    item.setSubmenu_(m)
    return bar


def run(files: list[str], snapshot: str | None = None) -> int:
    log(f"Subir no Drive {__version__} abrindo")
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    shell = Shell(files, snapshot)
    delegate = AppDelegate.alloc().init()
    delegate.shell = shell
    app.setDelegate_(delegate)
    app.setMainMenu_(_menu(delegate))
    AppHelper.runEventLoop()
    return 0
