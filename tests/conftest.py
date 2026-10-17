import os
import sys

# backend/app 패키지를 테스트에서 import 할 수 있게 한다
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
