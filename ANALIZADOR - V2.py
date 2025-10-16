import asyncio
import requests
import json
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
from datetime import datetime

# ---------- FUNCIONES UTILITARIAS ----------

def formatear_volumen(num):
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}b"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}m"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}k"
    else:
        return f"{num:.2f}"

def decimales_por_valor(valor):
    s = f"{valor:.10f}".rstrip('0')
    return len(s.split('.')[1]) if '.' in s else 0

def agrupar_precio_manual(price, agrupacion):
    agrupado = (price // agrupacion) * agrupacion
    decimales = decimales_por_valor(agrupacion)
    return round(agrupado, decimales)

# ---------- FUNCIONES DE ARCHIVO ----------

RUTA_ARCHIVO = "agrupaciones.txt"

def cargar_agrupaciones_guardadas():
    if os.path.exists(RUTA_ARCHIVO):
        try:
            with open(RUTA_ARCHIVO, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error al cargar agrupaciones guardadas: {e}")
    return {}

def guardar_agrupacion_individual(symbol, valor):
    agrupaciones = cargar_agrupaciones_guardadas()
    agrupaciones[symbol] = valor
    try:
        with open(RUTA_ARCHIVO, "w") as f:
            json.dump(agrupaciones, f, indent=4)
    except Exception as e:
        print(f"Error al guardar agrupaciones: {e}")

# ---------- OBTENER DATOS BINANCE ----------

def obtener_precio_actual(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        return float(requests.get(url).json()['price'])
    except Exception as e:
        print(f"Error al obtener precio actual para {symbol}: {e}")
        return None

def obtener_tick_size(symbol):
    url = f"https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        data = requests.get(url).json()
        for s in data["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "PRICE_FILTER":
                        tick_size = float(f["tickSize"])
                        return tick_size
        print(f"No se encontró tickSize para {symbol}")
        return 0.01
    except Exception as e:
        print(f"Error al obtener tickSize para {symbol}: {e}")
        return 0.01

def cargar_libro_ordenes_api(symbols, base_url="http://localhost:8000"):
    order_books = {}
    for symbol in symbols:
        try:
            resp = requests.get(f"{base_url}/orderbooks/{symbol}")
            if resp.status_code == 200:
                order_books[symbol] = resp.json()
            else:
                print(f"No se encontró libro para {symbol} (status {resp.status_code})")
        except Exception as e:
            print(f"Error al obtener libro para {symbol}: {e}")
    return order_books

# ---------- INTERFAZ GRÁFICA ----------

class OrderBookAnalyzerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Analizador de Libro de Órdenes - Binance Futures")
        self.root.geometry("1200x800")
        self.root.configure(bg='#1e293b')
        
        self.symbols = []
        self.selected_symbols = {}
        self.agrupaciones = cargar_agrupaciones_guardadas()
        self.tick_sizes = {}
        self.is_running = False
        self.analysis_task = None
        
        self.setup_ui()
        self.cargar_symbols()
        
    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#1e293b')
        style.configure('TLabel', background='#1e293b', foreground='white', font=('Arial', 10))
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'), foreground='#60a5fa')
        style.configure('TButton', font=('Arial', 10))
        style.configure('TCheckbutton', background='#1e293b', foreground='white')
        
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill='x', padx=20, pady=10)
        
        ttk.Label(header_frame, text="Analizador de Libro de Órdenes", 
                 style='Title.TLabel').pack(side='left')
        
        self.status_label = ttk.Label(header_frame, text="● Detenido", 
                                     foreground='#ef4444')
        self.status_label.pack(side='right', padx=10)
        
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=20, pady=5)
        
        self.start_button = tk.Button(control_frame, text="▶ Iniciar Análisis", 
                                      command=self.iniciar_analisis,
                                      bg='#22c55e', fg='white', font=('Arial', 11, 'bold'),
                                      relief='flat', padx=20, pady=8, cursor='hand2')
        self.start_button.pack(side='left', padx=5)
        
        self.stop_button = tk.Button(control_frame, text="⏸ Detener", 
                                     command=self.detener_analisis, state='disabled',
                                     bg='#ef4444', fg='white', font=('Arial', 11, 'bold'),
                                     relief='flat', padx=20, pady=8, cursor='hand2')
        self.stop_button.pack(side='left', padx=5)
        
        self.refresh_button = tk.Button(control_frame, text="🔄 Refrescar Símbolos", 
                                        command=self.cargar_symbols,
                                        bg='#3b82f6', fg='white', font=('Arial', 10),
                                        relief='flat', padx=15, pady=8, cursor='hand2')
        self.refresh_button.pack(side='left', padx=5)
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=20, pady=10)
        
        config_frame = ttk.Frame(self.notebook)
        self.notebook.add(config_frame, text="⚙ Configuración")
        
        canvas = tk.Canvas(config_frame, bg='#1e293b', highlightthickness=0)
        scrollbar = ttk.Scrollbar(config_frame, orient="vertical", command=canvas.yview)
        self.symbols_frame = ttk.Frame(canvas)
        
        self.symbols_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.symbols_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        results_frame = ttk.Frame(self.notebook)
        self.notebook.add(results_frame, text="📊 Resultados")
        
        self.results_text = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD,
                                                      bg='#0f172a', fg='white',
                                                      font=('Consolas', 10),
                                                      insertbackground='white')
        self.results_text.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.results_text.tag_configure('symbol', foreground='#60a5fa', font=('Consolas', 12, 'bold'))
        self.results_text.tag_configure('long', foreground='#22c55e', font=('Consolas', 10, 'bold'))
        self.results_text.tag_configure('short', foreground='#ef4444', font=('Consolas', 10, 'bold'))
        self.results_text.tag_configure('info', foreground='#94a3b8')
        
    def cargar_symbols(self):
        try:
            resp = requests.get("http://localhost:8000/symbols")
            data = resp.json()
            self.symbols = data.get("symbols", [])
            self.mostrar_symbols()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo conectar al servidor:\n{e}")
    
    def mostrar_symbols(self):
        for widget in self.symbols_frame.winfo_children():
            widget.destroy()
        
        ttk.Label(self.symbols_frame, text="Selecciona los símbolos a analizar:",
                 font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=3, pady=10, sticky='w')
        
        row = 1
        for symbol in self.symbols:
            symbol_frame = tk.Frame(self.symbols_frame, bg='#334155', relief='groove', bd=2)
            symbol_frame.grid(row=row, column=0, columnspan=3, sticky='ew', padx=5, pady=3)
            
            var = tk.BooleanVar()
            self.selected_symbols[symbol] = var
            
            cb = tk.Checkbutton(symbol_frame, text=symbol, variable=var,
                               bg='#334155', fg='white', selectcolor='#1e293b',
                               font=('Arial', 10, 'bold'), activebackground='#334155',
                               activeforeground='white')
            cb.pack(side='left', padx=10, pady=5)
            
            tk.Label(symbol_frame, text="Agrupación:", bg='#334155', 
                    fg='white', font=('Arial', 9)).pack(side='left', padx=(20, 5))
            
            entry = tk.Entry(symbol_frame, width=15, bg='#1e293b', fg='white',
                           insertbackground='white', font=('Arial', 10))
            entry.pack(side='left', padx=5, pady=5)
            
            if symbol in self.agrupaciones:
                entry.insert(0, str(self.agrupaciones[symbol]))
            
            entry.bind('<FocusOut>', lambda e, s=symbol, en=entry: self.guardar_agrupacion(s, en))
            
            row += 1
    
    def guardar_agrupacion(self, symbol, entry):
        try:
            valor = float(entry.get())
            guardar_agrupacion_individual(symbol, valor)
            self.agrupaciones[symbol] = valor
        except ValueError:
            pass
    
    def iniciar_analisis(self):
        symbols_elegidos = [sym for sym, var in self.selected_symbols.items() if var.get()]
        
        if not symbols_elegidos:
            messagebox.showwarning("Advertencia", "Selecciona al menos un símbolo")
            return
        
        faltantes = [sym for sym in symbols_elegidos if sym not in self.agrupaciones]
        if faltantes:
            messagebox.showwarning("Advertencia", 
                                  f"Se guardó la agrupación para:\n{', '.join(faltantes)}")
            return
        
        self.is_running = True
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.status_label.config(text="● Ejecutando", foreground='#22c55e')
        self.notebook.select(1)
        
        self.analysis_task = threading.Thread(target=self.ejecutar_analisis_loop, 
                                             args=(symbols_elegidos,), daemon=True)
        self.analysis_task.start()
    
    def detener_analisis(self):
        self.is_running = False
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.status_label.config(text="● Detenido", foreground='#ef4444')
    
    def ejecutar_analisis_loop(self, symbols_elegidos):
        while self.is_running:
            try:
                self.realizar_analisis(symbols_elegidos)
                for _ in range(1800):
                    if not self.is_running:
                        break
                    import time
                    time.sleep(1)
            except Exception as e:
                print(f"Error en análisis: {e}")
    
    def realizar_analisis(self, symbols_elegidos):
        self.limpiar_resultados()
        self.agregar_resultado(f"=== Análisis iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        
        for symbol in symbols_elegidos:
            if symbol not in self.tick_sizes:
                self.tick_sizes[symbol] = obtener_tick_size(symbol)
        
        order_books = cargar_libro_ordenes_api(symbols_elegidos)
        
        if not order_books:
            self.agregar_resultado("No hay datos disponibles. Esperando próximo ciclo...\n")
            return
        
        for symbol, order_book in order_books.items():
            agrupacion_manual = self.agrupaciones[symbol]
            tick = self.tick_sizes[symbol]
            decimales_tick = decimales_por_valor(tick)
            
            bid_ranges, ask_ranges = {}, {}
            
            for price, qty in order_book['bids'].items():
                price, qty = float(price), float(qty)
                range_key = agrupar_precio_manual(price, agrupacion_manual)
                if range_key not in bid_ranges:
                    bid_ranges[range_key] = {'total_qty': 0, 'price_count': {}}
                bid_ranges[range_key]['total_qty'] += qty
                bid_ranges[range_key]['price_count'][price] = bid_ranges[range_key]['price_count'].get(price, 0) + qty
            
            for price, qty in order_book['asks'].items():
                price, qty = float(price), float(qty)
                range_key = agrupar_precio_manual(price, agrupacion_manual)
                if range_key not in ask_ranges:
                    ask_ranges[range_key] = {'total_qty': 0, 'price_count': {}}
                ask_ranges[range_key]['total_qty'] += qty
                ask_ranges[range_key]['price_count'][price] = ask_ranges[range_key]['price_count'].get(price, 0) + qty
            
            top_bid_ranges = sorted(bid_ranges.items(), key=lambda x: x[1]['total_qty'], reverse=True)[:6]
            top_ask_ranges = sorted(ask_ranges.items(), key=lambda x: x[1]['total_qty'], reverse=True)[:6]
            
            top_bid_ranges = sorted(top_bid_ranges, key=lambda x: x[0], reverse=True)
            top_ask_ranges = sorted(top_ask_ranges, key=lambda x: x[0])
            
            self.agregar_resultado(f"{'='*50}\n", 'symbol')
            self.agregar_resultado(f"{symbol}\n", 'symbol')
            self.agregar_resultado(f"{'='*50}\n", 'symbol')
            self.agregar_resultado(f"(Agrupación: {agrupacion_manual}, TickSize: {tick})\n\n", 'info')
            
            self.agregar_resultado("🟢 Top Long Zones (Compra):\n", 'long')
            for pr_range, data in top_bid_ranges[2:]:
                total_qty = data['total_qty']
                if total_qty > 0:
                    weighted_avg_price = sum(p * q for p, q in data['price_count'].items()) / total_qty
                    weighted_avg_price = round(round(weighted_avg_price / tick) * tick, decimales_tick)
                else:
                    weighted_avg_price = 0
                volumen_formateado = formatear_volumen(total_qty)
                self.agregar_resultado(f"   Shock: {weighted_avg_price:.{decimales_tick}f} | Volumen: {volumen_formateado}\n")
            
            self.agregar_resultado("\n🔴 Top Short Zones (Venta):\n", 'short')
            for pr_range, data in top_ask_ranges[2:]:
                total_qty = data['total_qty']
                if total_qty > 0:
                    weighted_avg_price = sum(p * q for p, q in data['price_count'].items()) / total_qty
                    weighted_avg_price = round(round(weighted_avg_price / tick) * tick, decimales_tick)
                else:
                    weighted_avg_price = 0
                volumen_formateado = formatear_volumen(total_qty)
                self.agregar_resultado(f"   Shock: {weighted_avg_price:.{decimales_tick}f} | Volumen: {volumen_formateado}\n")
            
            self.agregar_resultado("\n\n")
        
        self.agregar_resultado(f"\n{'='*50}\n")
        self.agregar_resultado("Próxima actualización en 30 minutos...\n", 'info')
    
    def agregar_resultado(self, texto, tag=None):
        self.results_text.insert(tk.END, texto, tag)
        self.results_text.see(tk.END)
        self.root.update()
    
    def limpiar_resultados(self):
        self.results_text.delete('1.0', tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = OrderBookAnalyzerGUI(root)
    root.mainloop()