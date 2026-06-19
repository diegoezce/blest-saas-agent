#!/bin/bash

echo "🛑 Apagando servidor..."
pkill -9 -f "python run.py"

echo "⏳ Esperando..."
sleep 3

echo "🚀 Iniciando servidor..."
python run.py --web
