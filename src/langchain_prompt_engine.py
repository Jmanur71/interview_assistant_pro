"""LangChain-based prompt engine for detailed interview answers with few-shot learning"""

try:
    from langchain.prompts import FewShotChatMessagePromptTemplate, ChatPromptTemplate
except ImportError:
    # Fallback if langchain modules not available
    FewShotChatMessagePromptTemplate = None
    ChatPromptTemplate = None

# Few-shot examples that demonstrate the expected detailed format
DETAILED_ANSWER_EXAMPLES = [
    {
        "input": "What is Docker?",
        "output": """**Direct Answer**
Docker is a containerization platform that packages applications and their dependencies into isolated, portable containers that run consistently across any environment.

**Definition & Concept**
Docker uses OS-level virtualization to create lightweight containers - think of it like shipping containers for software. Each container includes your application, runtime, libraries, and configurations in a single package. Unlike VMs that require a full OS (1-15GB each), containers share the host OS kernel, making them lightweight (~5-100MB each) and fast to start (milliseconds).

**Key Benefits**
- Consistency: "Works on my machine" becomes "Works everywhere" - dev/staging/production use identical images
- Efficiency: 20-50x more containers than VMs on same hardware, 90% faster startup times
- Scalability: Deploy 100 containers as easily as 1, supports auto-scaling
- Isolation: Each container has its own filesystem, network, and processes - one failing container doesn't crash others
- Speed: 5-minute deployment cycles instead of 2 hours with VMs

**Real-World Scenario**
Scenario: E-commerce platform (50 developers, 100 daily deployments)
Problem: Inconsistent environments between laptop/staging/production caused 40% of bugs after deployment
Solution: Containerized entire stack - frontend, backend, database, cache all in Docker
Results: 95% fewer environment-related bugs, deployment time from 2 hours to 5 minutes, infrastructure costs down 60%

**Complete Setup Example**
CODEBLOCK: dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD curl -f http://localhost:8000/health || exit 1
CMD ["gunicorn", "--workers=4", "--bind=0.0.0.0:8000", "app:app"]
ENDCODEBLOCK

This Dockerfile creates a secure, production-grade container with health checks and proper user permissions.

**Step-by-Step Implementation**
Step 1: Create Dockerfile with the content above
Step 2: Build the image
CODE: docker build -t myapp:v1.0 .
Step 3: Test locally
CODE: docker run -p 8000:8000 myapp:v1.0
Step 4: Push to registry
CODE: docker tag myapp:v1.0 docker.io/username/myapp:v1.0 && docker push docker.io/username/myapp:v1.0
Step 5: Deploy to Kubernetes
CODEBLOCK: yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
      - name: myapp
        image: docker.io/username/myapp:v1.0
        ports:
        - containerPort: 8000
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
ENDCODEBLOCK

**Common Mistakes**
- Mistake 1: Running as root - Fix: Create non-root user for security
- Mistake 2: Large image sizes - Fix: Use .dockerignore, multi-stage builds, slim base images
- Mistake 3: No health checks - Fix: Add HEALTHCHECK instruction for production
- Mistake 4: Storing state in containers - Fix: Use volumes and external databases

**Performance & Scaling**
- Container startup: 50-200ms vs 30-60s for VMs
- Memory overhead: ~5-20MB per container vs 500MB-2GB per VM
- At scale: Netflix runs 1000s of containers daily, handles 300M+ requests

**Troubleshooting Commands**
CODE: docker logs -f container_name
CODE: docker exec -it container_name bash
CODE: docker stats
CODE: docker inspect container_name

**Companies Using Docker**
- Netflix: Docker + Kubernetes, deploy 4000+ times per day
- Airbnb: Containerized entire infrastructure, 99.9% uptime
- Spotify: 1000s of microservices in Docker

**TIP: Use Docker official base images (python:3.9-slim) instead of ubuntu/centos - they're security-patched, half the size, and optimized for containers.**"""
    }
]

class LangChainPromptEngine:
    """Uses LangChain for improved prompt engineering with few-shot examples"""
    
    @staticmethod
    def create_detailed_answer_prompt(question: str, resume_text: str = "") -> str:
        """Create a detailed answer prompt using LangChain with few-shot learning"""
        
        # System message setting the tone and expectations
        system_message = """You are a SENIOR DevOps architect and technical interview expert. 
Your answers MUST be comprehensive, detailed, and production-grade.

CRITICAL REQUIREMENTS:
1. Your answer MUST be 1500+ words of detailed content
2. Include ALL 12 sections below - NEVER skip any
3. Provide ACTUAL, WORKING CODE - not snippets
4. Include real company scenarios with metrics
5. Use exact formatting: CODEBLOCK: language ... ENDCODEBLOCK

MANDATORY 12-SECTION STRUCTURE:

1. **DIRECT ANSWER** (1-2 sentences answering the question)

2. **DEFINITION & CONCEPT** (2-3 detailed paragraphs)
   - Technical definition
   - How it works under the hood
   - Real-world analogy
   - Why it matters

3. **KEY BENEFITS** (5-7 detailed bullets)
   - Each with specific technical advantage and metrics
   - Include performance/cost numbers

4. **REAL-WORLD SCENARIO** (detailed company example)
   - Background (team size, daily workload)
   - Problem they faced
   - Solution they implemented
   - Results (concrete metrics)

5. **COMPLETE CODE EXAMPLE** (production-grade, working code)
   CODEBLOCK: [language]
   [ACTUAL working code with comments]
   ENDCODEBLOCK
   Then explain each section

6. **STEP-BY-STEP IMPLEMENTATION** (5-8 numbered steps)
   - Include actual commands
   - Include configuration details

7. **ADVANCED CONFIGURATION** (production setup)
   CODEBLOCK: yaml
   [full config with all options]
   ENDCODEBLOCK

8. **COMMON MISTAKES & FIXES** (4-5 specific mistakes)
   - Mistake → Why it's wrong → How to fix it

9. **PERFORMANCE & SCALING**
   - Scale from 10 to 10M users
   - Resource requirements
   - Optimization techniques

10. **DEBUGGING COMMANDS** (3-5 actual commands)
    CODE: command_here
    Explanation of what it does

11. **REAL COMPANIES USING THIS**
    - Specific company → Their use case → Results

12. **EXPERT TIP** (one powerful insight that shows mastery)

FORMAT REQUIREMENTS:
- Use CODEBLOCK: language for multi-line code
- Use CODE: command for single commands
- Use - for bullets
- Use **bold** for important terms
- NEVER use markdown backticks or triple quotes
- Provide actual, executable code"""

        if resume_text:
            system_message += f"\n\nCANDIDATE RESUME:\n{resume_text[:2000]}"
        
        user_prompt = f"""Please provide a comprehensive, expert-level answer to this interview question.

QUESTION: {question}

CRITICAL: Your answer MUST follow ALL 12 sections above. Include working code examples, real company scenarios with metrics, and step-by-step instructions. 
Aim for 1500+ words of detailed, production-grade content.
Do NOT provide brief answers - interviewers expect depth and expertise."""
        
        return f"{system_message}\n\n{user_prompt}"
    
    @staticmethod
    def get_few_shot_examples() -> str:
        """Return few-shot example to help model understand expected format"""
        examples = "\n\n".join([
            f"EXAMPLE INPUT: {ex['input']}\n"
            f"EXAMPLE OUTPUT:\n{ex['output']}"
            for ex in DETAILED_ANSWER_EXAMPLES
        ])
        return f"REFERENCE EXAMPLES OF EXPECTED FORMAT:\n{examples}"
