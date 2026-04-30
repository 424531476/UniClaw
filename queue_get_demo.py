"""
queue.Queue.get() 方法详解
演示 get() 方法的各种用法和特性
"""

import queue
import threading
import time


def get_basic():
    """get() 基本用法"""
    print("=" * 60)
    print("1. get() 基本用法")
    print("=" * 60)
    
    q = queue.Queue()
    
    # 添加数据
    q.put("第一个元素")
    q.put("第二个元素")
    q.put("第三个元素")
    
    print(f"队列大小: {q.qsize()}")
    
    # get() 默认行为：阻塞等待，直到有数据
    # FIFO（先进先出）顺序获取
    item1 = q.get()
    print(f"获取第1个: {item1}")
    
    item2 = q.get()
    print(f"获取第2个: {item2}")
    
    item3 = q.get()
    print(f"获取第3个: {item3}")
    
    print(f"队列是否为空: {q.empty()}\n")


def get_with_timeout():
    """get() 带超时参数"""
    print("=" * 60)
    print("2. get(timeout) - 带超时等待")
    print("=" * 60)
    
    q = queue.Queue()
    
    # 情况1: 队列为空，设置超时
    print("情况1: 队列为空时超时")
    try:
        item = q.get(timeout=2)  # 等待2秒
        print(f"获取到: {item}")
    except queue.Empty:
        print("❌ 超时！2秒内没有数据到达")
    
    # 情况2: 有数据时立即返回
    print("\n情况2: 队列有数据时立即返回")
    q.put("快速数据")
    start = time.time()
    item = q.get(timeout=5)  # 虽然有5秒超时，但会立即返回
    elapsed = time.time() - start
    print(f"✅ 获取到: {item} (耗时: {elapsed:.4f}秒)")
    
    # 情况3: 多线程中超时等待
    print("\n情况3: 多线程中的超时等待")
    q2 = queue.Queue()
    
    def delayed_producer():
        time.sleep(1.5)
        q2.put("延迟数据")
        print("[生产者] 数据已放入")
    
    thread = threading.Thread(target=delayed_producer)
    thread.start()
    
    print("[消费者] 开始等待（最多3秒）...")
    start = time.time()
    try:
        item = q2.get(timeout=3)
        elapsed = time.time() - start
        print(f"✅ 获取到: {item} (等待了 {elapsed:.2f}秒)")
    except queue.Empty:
        print("❌ 超时")
    
    thread.join()
    print()


def get_nowait():
    """get_nowait() 非阻塞获取"""
    print("=" * 60)
    print("3. get_nowait() - 非阻塞获取")
    print("=" * 60)
    
    q = queue.Queue()
    
    # 情况1: 队列为空时
    print("情况1: 队列为空")
    try:
        item = q.get_nowait()  # 等同于 get(block=False)
        print(f"获取到: {item}")
    except queue.Empty:
        print("❌ 队列为空，无法获取")
    
    # 情况2: 队列有数据时
    print("\n情况2: 队列有数据")
    q.put("即时数据")
    item = q.get_nowait()
    print(f"✅ 获取到: {item}")
    
    # 实际应用：轮询模式
    print("\n情况3: 轮询检查模式")
    q2 = queue.Queue()
    
    def producer():
        for i in range(3):
            time.sleep(0.5)
            q2.put(f"数据-{i+1}")
    
    thread = threading.Thread(target=producer)
    thread.start()
    
    # 非阻塞轮询
    for i in range(6):
        try:
            item = q2.get_nowait()
            print(f"  [轮询{i+1}] 获取到: {item}")
        except queue.Empty:
            print(f"  [轮询{i+1}] 队列为空")
        time.sleep(0.3)
    
    thread.join()
    print()


def get_with_task_done():
    """get() 配合 task_done() 使用"""
    print("=" * 60)
    print("4. get() + task_done() - 任务完成标记")
    print("=" * 60)
    
    q = queue.Queue()
    
    # 添加任务
    for i in range(5):
        q.put(f"任务-{i+1}")
    
    print(f"初始队列大小: {q.qsize()}")
    print(f"未完成的任务数: {q.unfinished_tasks}")
    
    def worker():
        while True:
            try:
                task = q.get(timeout=2)  # 获取任务
                print(f"  处理: {task}")
                time.sleep(0.3)  # 模拟处理时间
                q.task_done()  # 标记任务完成
            except queue.Empty:
                break
    
    # 启动工作线程
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    
    # 等待所有任务完成
    q.join()  # 阻塞直到所有任务都被标记为完成
    print(f"\n所有任务已完成！")
    print(f"未完成的任务数: {q.unfinished_tasks}")
    
    for t in threads:
        t.join()
    print()


def get_blocking_behavior():
    """get() 阻塞行为详解"""
    print("=" * 60)
    print("5. get() 阻塞行为对比")
    print("=" * 60)
    
    # block=True (默认): 阻塞等待
    print("block=True (默认): 阻塞等待")
    q1 = queue.Queue()
    
    def producer1():
        time.sleep(1)
        q1.put("阻塞获取的数据")
    
    t1 = threading.Thread(target=producer1)
    t1.start()
    
    print("  等待数据中...")
    start = time.time()
    item = q1.get(block=True)  # 显式指定阻塞
    elapsed = time.time() - start
    print(f"  ✅ 获取到: {item} (阻塞了 {elapsed:.2f}秒)")
    t1.join()
    
    # block=False: 不阻塞，立即抛出异常
    print("\nblock=False: 不阻塞，立即返回")
    q2 = queue.Queue()
    
    try:
        item = q2.get(block=False)  # 等同于 get_nowait()
        print(f"  获取到: {item}")
    except queue.Empty:
        print("  ❌ 队列为空，立即抛出 Empty 异常")
    
    print()


def get_multithread_example():
    """get() 多线程实际应用"""
    print("=" * 60)
    print("6. get() 多线程实际应用 - 任务分发系统")
    print("=" * 60)
    
    task_queue = queue.Queue()
    result_queue = queue.Queue()
    
    def producer():
        """生产者：生成任务"""
        for i in range(10):
            task = f"任务-{i+1}"
            task_queue.put(task)
            print(f"[生产者] 创建: {task}")
            time.sleep(0.1)
    
    def worker(worker_id):
        """工作者：处理任务"""
        while True:
            try:
                task = task_queue.get(timeout=2)  # 阻塞等待任务
                print(f"[Worker-{worker_id}] 处理: {task}")
                time.sleep(0.3)  # 模拟处理
                
                result = f"{task}-完成"
                result_queue.put(result)
                
                task_queue.task_done()  # 标记任务完成
            except queue.Empty:
                print(f"[Worker-{worker_id}] 无更多任务，退出")
                break
    
    def consumer():
        """消费者：收集结果"""
        completed = 0
        while completed < 10:
            try:
                result = result_queue.get(timeout=3)
                print(f"[消费者] 收到结果: {result}")
                completed += 1
                result_queue.task_done()
            except queue.Empty:
                break
    
    # 启动线程
    producer_thread = threading.Thread(target=producer)
    worker_threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    consumer_thread = threading.Thread(target=consumer)
    
    producer_thread.start()
    for t in worker_threads:
        t.start()
    consumer_thread.start()
    
    # 等待完成
    producer_thread.join()
    task_queue.join()
    consumer_thread.join()
    for t in worker_threads:
        t.join()
    
    print(f"\n所有任务处理完毕！\n")


if __name__ == "__main__":
    get_basic()
    get_with_timeout()
    get_nowait()
    get_with_task_done()
    get_blocking_behavior()
    get_multithread_example()
    
    print("=" * 60)
    print("📚 get() 方法总结")
    print("=" * 60)
    print("""
核心特性:
  • FIFO 顺序：先进先出
  • 线程安全：可在多线程环境安全使用
  • 阻塞机制：默认阻塞等待，可设置超时
  
常用形式:
  1. q.get()                    # 阻塞等待，直到有数据
  2. q.get(timeout=5)           # 最多等待5秒
  3. q.get(block=False)         # 不阻塞，立即返回或抛异常
  4. q.get_nowait()             # 等同于 get(block=False)
  
最佳实践:
  • 生产环境建议使用 timeout 避免永久阻塞
  • 配合 task_done() 和 join() 实现任务跟踪
  • 多线程场景下注意异常处理
    """)
    print("=" * 60)
