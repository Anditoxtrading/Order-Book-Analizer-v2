# -*- coding: utf-8 -*-
import asyncio
import requests
import json
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
from datetime import datetime
from collections import defaultdict, Counter

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

# ---------- MÉTODOS DE CÁLCULO QUIRÚRGICO ----------

def calcular_precio_moda(price_count, tick, decimales_tick):
    """Encuentra el precio con mayor volumen (más quirúrgico)"""
    if not price_count:
        return 0
    precio_max = max(price_count.items(), key=lambda x: x[1])[0]
    return round(round(precio_max / tick) * tick, decimales_tick)

def calcular_precio_mediana_ponderada(price_count, tick, decimales_tick):
    """Calcula la mediana ponderada por volumen"""
    if not price_count:
        return 0
    
    # Ordenar precios
    sorted_prices = sorted(price_count.items())
    total_qty = sum(qty for _, qty in sorted_prices)
    target_qty = total_qty / 2
    
    cumulative = 0
    for price, qty in sorted_prices:
        cumulative += qty
        if cumulative >= target_qty:
            return round(round(price / tick) * tick, decimales_tick)
    
    return round(round(sorted_prices[-1][0] / tick) * tick, decimales_tick)

def calcular_precio_densidad_maxima(price_count, tick, decimales_tick, ventana_porcentaje=0.05):
    """Encuentra el área con mayor densidad de órdenes (ventana deslizante)"""
    if not price_count:
        return 0
    
    sorted_prices = sorted(price_count.items())
    if len(sorted_prices) < 2:
        return calcular_precio_moda(price_count, tick, decimales_tick)
    
    # Calcular rango de precios
    min_price = sorted_prices[0][0]
    max_price = sorted_prices[-1][0]
    ventana = (max_price - min_price) * ventana_porcentaje
    
    max_densidad = 0
    mejor_precio = sorted_prices[0][0]
    
    # Ventana deslizante
    for precio_central, _ in sorted_prices:
        densidad = sum(qty for p, qty in sorted_prices 
                      if abs(p - precio_central) <= ventana)
        
        if densidad > max_densidad:
            max_densidad = densidad
            mejor_precio = precio_central
    
    return round(round(mejor_precio / tick) * tick, decimales_tick)

def calcular_precio_clustering(price_count, tick, decimales_tick):
    """Agrupa precios cercanos y encuentra el centro del cluster más grande"""
    if not price_count:
        return 0
    
    sorted_prices = sorted(price_count.items())
    
    # Agrupar precios cercanos (dentro de 3 ticks)
    clusters = []
    current_cluster = [sorted_prices[0]]
    
    for i in range(1, len(sorted_prices)):
        if sorted_prices[i][0] - current_cluster[-1][0] <= tick * 3:
            current_cluster.append(sorted_prices[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [sorted_prices[i]]
    
    if current_cluster:
        clusters.append(current_cluster)
    
    # Encontrar el cluster con mayor volumen total
    mejor_cluster = max(clusters, key=lambda c: sum(qty for _, qty in c))
    
    # Calcular el centro ponderado del mejor cluster
    total_qty = sum(qty for _, qty in mejor_cluster)
    weighted_price = sum(p * qty for p, qty in mejor_cluster) / total_qty
    
    return round(round(weighted_price / tick) * tick, decimales_tick)

def calcular_precio_promedio_ponderado(price_count, tick, decimales_tick):
    """Método original - promedio ponderado"""
    if not price_count:
        return 0
    
    total_qty = sum(price_count.values())
    weighted_avg = sum(p * q for p, q in price_count.items()) / total_qty
    return round(round(weighted_avg / tick) * tick, decimales_tick)

# ---------- FUNCIONES DE ARCHIVO ----------

RUTA_ARCHIVO = "agrupaciones.txt"
RUTA_SHOCKS = "shocks_guardados.txt"

def cargar_agrupaciones_guardadas():
    if os.path.exists(RUTA_ARCHIVO):
        try:
            with open(RUTA_ARCHIVO, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error al cargar agrupaciones: {e}")
    return {}

def guardar_agrupacion_individual(symbol, valor):
    agrupaciones = cargar_agrupaciones_guardadas()
    agrupaciones[symbol] = valor
    try:
        with open(RUTA_ARCHIVO, "w") as f:
            json.dump(agrupaciones, f, indent=4)
    except Exception as e:
        print(f"Error al guardar agrupaciones: {e}")

def guardar_puntos_shocks(datos_shocks):
    try:
        with open(RUTA_SHOCKS, "a", encoding='utf-8') as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n--- Analisis guardado: {timestamp} ---\n")
            for linea in datos_shocks:
                f.write(f"{linea}\n")
            f.write("\n")
        return True
    except Exception as e:
        print(f"Error al guardar puntos shocks: {e}")
        return False

# ---------- OBTENER DATOS BINANCE ----------

def obtener_precio_actual(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        return float(requests.get(url).json()['price'])
    except Exception as e:
        print(f"Error al obtener precio: {e}")
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
        return 0.01
    except Exception as e:
        print(f"Error al obtener tickSize: {e}")
        return 0.01

def cargar_libro_ordenes_api(symbols, base_url="http://localhost:8000"):
    order_books = {}
    for symbol in symbols:
        try:
            resp = requests.get(f"{base_url}/orderbooks/{symbol}")
            if resp.status_code == 200:
                order_books[symbol] = resp.json()
        except Exception as e:
            print(f"Error al obtener libro: {e}")
    return order_books

# ---------- INTERFAZ GRAFICA ----------

class OrderBookAnalyzerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Analizador de Libro de Ordenes - Binance Futures")
        self.root.geometry("1200x850")
        self.root.configure(bg='#1e293b')
        
        self.symbols = []
        self.selected_symbols = {}
        self.agrupaciones = cargar_agrupaciones_guardadas()
        self.tick_sizes = {}
        self.is_running = False
        self.analysis_task = None
        
        # Método de cálculo seleccionado
        self.metodo_calculo = tk.StringVar(value="densidad_maxima")
        
        self.shocks_actuales = defaultdict(lambda: {'long': [], 'short': []})
        self.shocks_seleccionados = defaultdict(lambda: {'long': None, 'short': None})
        
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
        style.configure('TRadiobutton', background='#1e293b', foreground='white')
        
        # Header
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill='x', padx=20, pady=10)
        
        ttk.Label(header_frame, text="Analizador de Libro de Ordenes", 
                 style='Title.TLabel').pack(side='left')
        
        self.status_label = ttk.Label(header_frame, text="Detenido", 
                                     foreground='#ef4444')
        self.status_label.pack(side='right', padx=10)
        
        # Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=20, pady=5)
        
        self.start_button = tk.Button(control_frame, text="Iniciar Analisis", 
                                      command=self.iniciar_analisis,
                                      bg='#22c55e', fg='white', font=('Arial', 11, 'bold'),
                                      relief='flat', padx=20, pady=8, cursor='hand2')
        self.start_button.pack(side='left', padx=5)
        
        self.stop_button = tk.Button(control_frame, text="Detener", 
                                     command=self.detener_analisis, state='disabled',
                                     bg='#ef4444', fg='white', font=('Arial', 11, 'bold'),
                                     relief='flat', padx=20, pady=8, cursor='hand2')
        self.stop_button.pack(side='left', padx=5)
        
        self.refresh_button = tk.Button(control_frame, text="Refrescar Simbolos", 
                                        command=self.cargar_symbols,
                                        bg='#3b82f6', fg='white', font=('Arial', 10),
                                        relief='flat', padx=15, pady=8, cursor='hand2')
        self.refresh_button.pack(side='left', padx=5)
        
        self.save_button = tk.Button(control_frame, text="Guardar Puntos", 
                                     command=self.guardar_analisis, state='disabled',
                                     bg='#f59e0b', fg='white', font=('Arial', 10, 'bold'),
                                     relief='flat', padx=15, pady=8, cursor='hand2')
        self.save_button.pack(side='left', padx=5)
        
        # Selector de método
        metodo_frame = tk.Frame(control_frame, bg='#334155', relief='groove', bd=2)
        metodo_frame.pack(side='left', padx=20)
        
        tk.Label(metodo_frame, text="Método:", bg='#334155', fg='white',
                font=('Arial', 9, 'bold')).pack(side='left', padx=5)
        
        metodos = [
            ("🎯 Densidad Máx", "densidad_maxima"),
            ("📍 Moda", "moda"),
            ("🎲 Clustering", "clustering"),
            ("📊 Mediana", "mediana"),
            ("📈 Promedio", "promedio")
        ]
        
        for texto, valor in metodos:
            rb = tk.Radiobutton(metodo_frame, text=texto, variable=self.metodo_calculo,
                              value=valor, bg='#334155', fg='white', selectcolor='#1e293b',
                              activebackground='#334155', activeforeground='white',
                              font=('Arial', 8))
            rb.pack(side='left', padx=3)
        
        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=20, pady=10)
        
        # Tab 1: Configuracion
        config_frame = ttk.Frame(self.notebook)
        self.notebook.add(config_frame, text="Configuracion")
        
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
        
        # Tab 2: Resultados
        results_frame = ttk.Frame(self.notebook)
        self.notebook.add(results_frame, text="Resultados")
        
        # Info de instrucciones
        info_frame = tk.Frame(results_frame, bg='#334155', relief='groove', bd=2)
        info_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Label(info_frame, text="💡 Haz clic en los precios para seleccionar/deseleccionar • Cambia el método de cálculo arriba", 
                bg='#334155', fg='#fbbf24', font=('Arial', 10, 'bold')).pack(pady=8)
        
        self.results_text = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD,
                                                      bg='#0f172a', fg='white',
                                                      font=('Consolas', 10),
                                                      insertbackground='white',
                                                      cursor='hand2')
        self.results_text.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Tags de estilo
        self.results_text.tag_configure('symbol', foreground='#60a5fa', font=('Consolas', 12, 'bold'))
        self.results_text.tag_configure('long', foreground='#22c55e', font=('Consolas', 10, 'bold'))
        self.results_text.tag_configure('short', foreground='#ef4444', font=('Consolas', 10, 'bold'))
        self.results_text.tag_configure('info', foreground='#94a3b8')
        self.results_text.tag_configure('metodo', foreground='#a78bfa', font=('Consolas', 9, 'italic'))
        self.results_text.tag_configure('clickable', foreground='#fbbf24', underline=1)
        self.results_text.tag_configure('selected', background='#3b82f6', foreground='white')
        
        # Bind de clic
        self.results_text.tag_bind('clickable', '<Button-1>', self.on_shock_click)
        self.results_text.tag_bind('clickable', '<Enter>', lambda e: self.results_text.config(cursor='hand2'))
        self.results_text.tag_bind('clickable', '<Leave>', lambda e: self.results_text.config(cursor='arrow'))
        
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
        
        ttk.Label(self.symbols_frame, text="Selecciona los simbolos a analizar:",
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
            
            tk.Label(symbol_frame, text="Agrupacion:", bg='#334155', 
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
    
    def calcular_precio_segun_metodo(self, price_count, tick, decimales_tick):
        """Calcula el precio según el método seleccionado"""
        metodo = self.metodo_calculo.get()
        
        if metodo == "moda":
            return calcular_precio_moda(price_count, tick, decimales_tick)
        elif metodo == "mediana":
            return calcular_precio_mediana_ponderada(price_count, tick, decimales_tick)
        elif metodo == "densidad_maxima":
            return calcular_precio_densidad_maxima(price_count, tick, decimales_tick)
        elif metodo == "clustering":
            return calcular_precio_clustering(price_count, tick, decimales_tick)
        else:  # promedio
            return calcular_precio_promedio_ponderado(price_count, tick, decimales_tick)
    
    def iniciar_analisis(self):
        symbols_elegidos = [sym for sym, var in self.selected_symbols.items() if var.get()]
        
        if not symbols_elegidos:
            messagebox.showwarning("Advertencia", "Selecciona al menos un simbolo")
            return
        
        faltantes = [sym for sym in symbols_elegidos if sym not in self.agrupaciones]
        if faltantes:
            messagebox.showwarning("Advertencia", 
                                  f"Se guardo la agrupacion para:\n{', '.join(faltantes)}")
            return
        
        self.is_running = True
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.status_label.config(text="Ejecutando", foreground='#22c55e')
        self.notebook.select(1)
        
        self.analysis_task = threading.Thread(target=self.ejecutar_analisis_loop, 
                                             args=(symbols_elegidos,), daemon=True)
        self.analysis_task.start()
    
    def detener_analisis(self):
        self.is_running = False
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.status_label.config(text="Detenido", foreground='#ef4444')
        self.save_button.config(state='normal')
    
    def ejecutar_analisis_loop(self, symbols_elegidos):
        while self.is_running:
            try:
                self.realizar_analisis(symbols_elegidos)
                for _ in range(60):
                    if not self.is_running:
                        break
                    import time
                    time.sleep(1)
            except Exception as e:
                print(f"Error en analisis: {e}")
    
    def realizar_analisis(self, symbols_elegidos):
        self.limpiar_resultados()
        
        metodo_nombre = {
            "densidad_maxima": "Densidad Máxima",
            "moda": "Moda (Mayor Volumen)",
            "clustering": "Clustering",
            "mediana": "Mediana Ponderada",
            "promedio": "Promedio Ponderado"
        }
        
        self.agregar_resultado(f"=== Analisis iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        self.agregar_resultado(f"Método: {metodo_nombre[self.metodo_calculo.get()]}\n\n", 'metodo')
        
        for symbol in symbols_elegidos:
            if symbol not in self.tick_sizes:
                self.tick_sizes[symbol] = obtener_tick_size(symbol)
        
        order_books = cargar_libro_ordenes_api(symbols_elegidos)
        
        if not order_books:
            self.agregar_resultado("No hay datos disponibles.\n")
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
            self.agregar_resultado(f"(Agrupacion: {agrupacion_manual}, TickSize: {tick})\n\n", 'info')
            
            self.agregar_resultado("Long Zones (Compra):\n", 'long')
            long_shocks = []
            for pr_range, data in top_bid_ranges[2:]:
                precio_calculado = self.calcular_precio_segun_metodo(
                    data['price_count'], tick, decimales_tick
                )
                volumen_formateado = formatear_volumen(data['total_qty'])
                long_shocks.append(precio_calculado)
                
                self.agregar_resultado(f"   Shock: ")
                precio_str = f"{precio_calculado:.{decimales_tick}f}"
                tag_id = f"{symbol}_long_{precio_calculado}"
                self.agregar_resultado(precio_str, ('clickable', tag_id))
                self.agregar_resultado(f" | Vol: {volumen_formateado}\n")
            
            self.agregar_resultado("\nShort Zones (Venta):\n", 'short')
            short_shocks = []
            for pr_range, data in top_ask_ranges[2:]:
                precio_calculado = self.calcular_precio_segun_metodo(
                    data['price_count'], tick, decimales_tick
                )
                volumen_formateado = formatear_volumen(data['total_qty'])
                short_shocks.append(precio_calculado)
                
                self.agregar_resultado(f"   Shock: ")
                precio_str = f"{precio_calculado:.{decimales_tick}f}"
                tag_id = f"{symbol}_short_{precio_calculado}"
                self.agregar_resultado(precio_str, ('clickable', tag_id))
                self.agregar_resultado(f" | Vol: {volumen_formateado}\n")
            
            self.shocks_actuales[symbol] = {'long': long_shocks, 'short': short_shocks}
            self.agregar_resultado("\n\n")

    def on_shock_click(self, event):
        index = self.results_text.index(f"@{event.x},{event.y}")
        tags = self.results_text.tag_names(index)
        
        tag_id = None
        for tag in tags:
            if tag.startswith(tuple(self.symbols)):
                tag_id = tag
                break
        
        if not tag_id:
            return
        
        parts = tag_id.split('_')
        if len(parts) < 3:
            return
        
        symbol = parts[0]
        tipo = parts[1]
        precio = float('_'.join(parts[2:]))
        
        current_selection = self.shocks_seleccionados[symbol][tipo]
        
        if current_selection == precio:
            self.shocks_seleccionados[symbol][tipo] = None
            self.results_text.tag_remove('selected', f"{tag_id}.first", f"{tag_id}.last")
        else:
            if current_selection is not None:
                old_tag = f"{symbol}_{tipo}_{current_selection}"
                self.results_text.tag_remove('selected', f"{old_tag}.first", f"{old_tag}.last")
            
            self.shocks_seleccionados[symbol][tipo] = precio
            self.results_text.tag_add('selected', f"{tag_id}.first", f"{tag_id}.last")
    
    def agregar_resultado(self, texto, tag=None):
        if isinstance(tag, tuple):
            self.results_text.insert(tk.END, texto, tag)
        else:
            self.results_text.insert(tk.END, texto, tag)
        self.results_text.see(tk.END)
        self.root.update()
    
    def limpiar_resultados(self):
        self.results_text.delete('1.0', tk.END)
        self.shocks_seleccionados.clear()
    
    def guardar_analisis(self):
        datos_a_guardar = []
        
        for symbol in self.shocks_actuales.keys():
            long_price = self.shocks_seleccionados[symbol].get('long', None)
            short_price = self.shocks_seleccionados[symbol].get('short', None)
            
            long_str = str(long_price) if long_price is not None else ""
            short_str = str(short_price) if short_price is not None else ""
            
            if long_str or short_str:
                linea = f"{symbol} {long_str} {short_str}"
                datos_a_guardar.append(linea)
        
        if not datos_a_guardar:
            messagebox.showwarning("Advertencia", "Selecciona al menos un punto shock haciendo clic en los precios")
            return
        
        if guardar_puntos_shocks(datos_a_guardar):
            messagebox.showinfo("Exito", f"Se guardaron {len(datos_a_guardar)} lineas en {RUTA_SHOCKS}")
        else:
            messagebox.showerror("Error", "No se pudo guardar el archivo")

if __name__ == "__main__":
    root = tk.Tk()
    app = OrderBookAnalyzerGUI(root)
    root.mainloop()
