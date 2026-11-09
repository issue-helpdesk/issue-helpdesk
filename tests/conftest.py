import os
import sys

# backend/app 패키지를 테스트에서 import 할 수 있게 한다
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# 서버 시작 검사가 요구하는 값. .env 를 읽기 전에 넣어 테스트가 실제 비밀값을 쓰지 않게 한다
os.environ.setdefault('JWT_SECRET', 'test-secret-test-secret-test-secret-0123')
